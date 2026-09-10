"use client";

import { Suspense, useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Sparkles, useAnimations, useGLTF } from "@react-three/drei";
import * as THREE from "three";

import {
  ATOM_IDLE_TIME_SCALE,
  getIdleAtomAnimationNames,
} from "@/lib/atomAnimation";

type AtomSceneProps = {
  activeStep: number;
  reducedMotion: boolean;
};

type AtomModelProps = AtomSceneProps;

const ELECTRON_NAMES = Array.from({ length: 7 }, (_, index) =>
  `Electron_${String(index + 1).padStart(2, "0")}`
);

function AtomModel({ activeStep, reducedMotion }: AtomModelProps) {
  const source = useGLTF("/models/expensum-atom-animated.glb");
  const groupRef = useRef<THREE.Group>(null);
  const electronRefs = useRef<THREE.Object3D[]>([]);
  const haloRef = useRef<THREE.Sprite>(null);
  const cameraTarget = useRef(new THREE.Vector3(0, 0, 0));
  const desiredTarget = useRef(new THREE.Vector3(0, 0, 0));
  const desiredCamera = useRef(new THREE.Vector3(6.4, 2.8, 7.8));
  const lastFocusedStep = useRef(activeStep);

  const haloTexture = useMemo(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 128;
    canvas.height = 128;
    const context = canvas.getContext("2d");
    if (context) {
      const gradient = context.createRadialGradient(64, 64, 3, 64, 64, 62);
      gradient.addColorStop(0, "rgba(217,255,248,0.95)");
      gradient.addColorStop(0.16, "rgba(95,196,203,0.68)");
      gradient.addColorStop(0.48, "rgba(95,196,203,0.18)");
      gradient.addColorStop(1, "rgba(95,196,203,0)");
      context.fillStyle = gradient;
      context.fillRect(0, 0, 128, 128);
    }
    return new THREE.CanvasTexture(canvas);
  }, []);

  const { actions } = useAnimations(source.animations, groupRef);

  useEffect(() => {
    const idleNames = new Set(getIdleAtomAnimationNames(source.animations.map((clip) => clip.name)));
    Object.entries(actions).forEach(([name, action]) => {
      if (!action || !idleNames.has(name)) return;
      action
        .reset()
        .setLoop(THREE.LoopRepeat, Infinity)
        .setEffectiveTimeScale(ATOM_IDLE_TIME_SCALE);
      if (reducedMotion) {
        action.stop();
      } else {
        action.play();
      }
    });

    return () => {
      Object.values(actions).forEach((action) => action?.stop());
    };
  }, [actions, reducedMotion, source.animations]);

  const scene = useMemo(() => {
    const nextScene = source.scene.clone(true);
    nextScene.traverse((object) => {
      if (object instanceof THREE.Light) {
        if (object.name.startsWith("Light_Electron_")) {
          // Queste luci sono figlie degli elettroni: devono restare attive per
          // seguire il loro movimento, ma con un'intensità più morbida.
          object.visible = true;
          object.intensity = 8;
          if (object instanceof THREE.PointLight) {
            object.distance = 3.6;
            object.decay = 2;
          }
        } else {
          // La luce principale del GLB viene sostituita dalle luci controllate
          // direttamente dalla scena React.
          object.visible = false;
        }
        return;
      }
      if (!(object instanceof THREE.Mesh)) return;
      object.material = Array.isArray(object.material)
        ? object.material.map((material) => material.clone())
        : object.material.clone();
      object.castShadow = true;
      object.receiveShadow = true;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach((material) => {
        if (!(material instanceof THREE.MeshStandardMaterial)) return;
        if (object.name.startsWith("Orbit_")) {
          material.color.set("#284247");
          material.metalness = 0.28;
          material.roughness = 0.68;
          material.transparent = true;
          material.opacity = 0.26;
          material.depthWrite = false;
        }
        if (object.name.startsWith("Electron_")) {
          material.color.set("#5fc4cb");
          material.emissive.set("#5fc4cb");
          material.emissiveIntensity = 1.45;
        }
      });
    });
    return nextScene;
  }, [source.scene]);

  useEffect(() => {
    electronRefs.current = ELECTRON_NAMES
      .map((name) => scene.getObjectByName(name))
      .filter((object): object is THREE.Object3D => Boolean(object));
  }, [scene]);

  useFrame((state, delta) => {
    const group = groupRef.current;
    if (!group) return;

    group.updateMatrixWorld();

    electronRefs.current.forEach((electron, index) => {
      const selected = index === activeStep;
      const targetScale = selected ? 1.48 : 1;
      const scale = THREE.MathUtils.damp(electron.scale.x, targetScale, 5, delta);
      electron.scale.setScalar(scale);

      const meshes: THREE.Mesh[] = [];
      electron.traverse((child) => {
        if (child instanceof THREE.Mesh) meshes.push(child);
      });
      meshes.forEach((mesh) => {
        const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        materials.forEach((material) => {
          if (!(material instanceof THREE.MeshStandardMaterial)) return;
          material.color.set(selected ? "#d9fff8" : "#5fc4cb");
          material.emissive.set(selected ? "#b9fff2" : "#5fc4cb");
          material.emissiveIntensity = THREE.MathUtils.damp(
            material.emissiveIntensity,
            selected ? 5.2 : 1.45,
            6,
            delta
          );
        });
      });
    });

    const activeElectron = electronRefs.current[activeStep];
    if (activeElectron) {
      const worldPosition = activeElectron.getWorldPosition(new THREE.Vector3());

      if (haloRef.current) {
        haloRef.current.position.copy(group.worldToLocal(worldPosition.clone()));
      }

      // Il focus avviene una sola volta per step: la camera non insegue
      // l'elettrone durante l'orbita, ma lo raggiunge con uno zoom morbido.
      if (activeStep !== lastFocusedStep.current) {
        const outward = worldPosition.clone().normalize();
        desiredTarget.current.copy(worldPosition).multiplyScalar(0.72);
        desiredCamera.current
          .copy(worldPosition)
          .add(outward.multiplyScalar(state.size.width < 800 ? 4.8 : 5.4))
          .add(new THREE.Vector3(0, 0.38, 0));
        lastFocusedStep.current = activeStep;
      }
    }

    const positionDamping = reducedMotion ? 14 : 1.8;
    const targetDamping = reducedMotion ? 14 : 1.65;
    cameraTarget.current.x = THREE.MathUtils.damp(
      cameraTarget.current.x,
      desiredTarget.current.x,
      targetDamping,
      delta
    );
    cameraTarget.current.y = THREE.MathUtils.damp(
      cameraTarget.current.y,
      desiredTarget.current.y,
      targetDamping,
      delta
    );
    cameraTarget.current.z = THREE.MathUtils.damp(
      cameraTarget.current.z,
      desiredTarget.current.z,
      targetDamping,
      delta
    );
    state.camera.position.x = THREE.MathUtils.damp(
      state.camera.position.x,
      desiredCamera.current.x,
      positionDamping,
      delta
    );
    state.camera.position.y = THREE.MathUtils.damp(
      state.camera.position.y,
      desiredCamera.current.y,
      positionDamping,
      delta
    );
    state.camera.position.z = THREE.MathUtils.damp(
      state.camera.position.z,
      desiredCamera.current.z,
      positionDamping,
      delta
    );
    state.camera.lookAt(cameraTarget.current);
  });

  return (
    <group ref={groupRef} scale={0.94}>
      <primitive object={scene} />
      <sprite ref={haloRef} scale={[1.25, 1.25, 1.25]}>
        <spriteMaterial
          map={haloTexture}
          transparent
          opacity={0.82}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </sprite>
    </group>
  );
}

function SceneFallback() {
  return (
    <mesh>
      <sphereGeometry args={[1.15, 48, 48]} />
      <meshStandardMaterial color="#5fc4cb" emissive="#5fc4cb" emissiveIntensity={1.8} />
    </mesh>
  );
}

export default function AtomScene({ activeStep, reducedMotion }: AtomSceneProps) {
  return (
    <Canvas
      camera={{ position: [6.4, 2.8, 7.8], fov: 42, near: 0.1, far: 100 }}
      dpr={[1, 1.35]}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
    >
      <ambientLight intensity={0.62} />
      <Sparkles count={reducedMotion ? 24 : 68} scale={[9, 7, 7]} size={1.4} speed={reducedMotion ? 0 : 0.18} opacity={0.45} color="#8ce2df" />
      <Suspense fallback={<SceneFallback />}>
        <AtomModel activeStep={activeStep} reducedMotion={reducedMotion} />
      </Suspense>
    </Canvas>
  );
}
