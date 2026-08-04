"""
recompute_gamification_xp.py — Riallinea l'XP degli utenti dopo una ricalibrazione.

`xp_awarded` e `total_xp` sono istantanee: il registry viene letto una volta sola,
allo sblocco, e poi il numero resta congelato a database. Cambiare un valore in
`src/gamification/registry.py` quindi **non è retroattivo** — senza questo script la
nuova taratura varrebbe solo per gli sblocchi futuri, e due utenti con gli stessi
badge finirebbero con XP diversi a seconda di quando li hanno presi.

Cosa tocca: solo `xp_awarded`, `total_xp` e `level`. Non sfiora `unlocked_at`,
`seen_at`, `notified_telegram` né `source`: la storia di cosa l'utente ha fatto e
quando resta intatta, cambia solo quanto vale.

Idempotente e rieseguibile.

Usa:
    python scripts/recompute_gamification_xp.py --dry-run   # mostra cosa cambierebbe
    python scripts/recompute_gamification_xp.py             # applica
    python scripts/recompute_gamification_xp.py --chat-id 123
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import Config
from src.gamification import backfill
from src.gamification.registry import BY_CODE
from src.gamification.xp import level_for_xp
from src.user_store import User, UserAchievement, UserGamificationProfile, UserStore


def _preview(store: UserStore, chat_ids: list[str]) -> None:
    """Mostra l'effetto del ricalcolo senza scrivere nulla.

    Legge gli sblocchi e ricalcola in memoria, così si può decidere *prima* se una
    ricalibrazione è accettabile — soprattutto guardando chi perde un livello.
    """
    saliti, scesi, invariati = [], [], 0
    sconosciuti: set[str] = set()

    with store.Session() as session:
        for chat_id in chat_ids:
            rows = session.query(UserAchievement).filter_by(chat_id=chat_id).all()
            if not rows:
                continue
            profile = session.query(UserGamificationProfile).filter_by(
                chat_id=chat_id
            ).first()
            vecchio_xp = (profile.total_xp if profile else 0) or 0
            vecchio_liv = (profile.level if profile else 1) or 1

            nuovo_xp = 0
            for row in rows:
                definition = BY_CODE.get(row.code)
                if definition is None:
                    sconosciuti.add(row.code)
                    nuovo_xp += row.xp_awarded or 0
                else:
                    nuovo_xp += definition.xp
            nuovo_liv = level_for_xp(nuovo_xp)

            riga = (chat_id, vecchio_xp, nuovo_xp, vecchio_liv, nuovo_liv, len(rows))
            if nuovo_liv > vecchio_liv:
                saliti.append(riga)
            elif nuovo_liv < vecchio_liv:
                scesi.append(riga)
            else:
                invariati += 1

    print(f"[recompute-xp] (dry-run) {len(chat_ids)} utenti esaminati.\n")
    if scesi:
        print(f"  ⚠  {len(scesi)} utenti PERDONO un livello:")
        for cid, vx, nx, vl, nl, n in scesi:
            print(f"     {cid:20} {vx:6} -> {nx:6} XP   livello {vl} -> {nl}   ({n} badge)")
        print()
    if saliti:
        print(f"  {len(saliti)} utenti salgono di livello:")
        for cid, vx, nx, vl, nl, n in saliti:
            print(f"     {cid:20} {vx:6} -> {nx:6} XP   livello {vl} -> {nl}   ({n} badge)")
        print()
    print(f"  {invariati} utenti restano allo stesso livello.")
    if sconosciuti:
        print(f"\n  Codici non più nel registry (XP lasciato invariato): {', '.join(sorted(sconosciuti))}")
    print("\n[recompute-xp] (dry-run) Nessuna scrittura effettuata.")


def main() -> None:
    """Riallinea l'XP ai valori attuali del registry."""
    parser = argparse.ArgumentParser(
        description="Riallinea l'XP degli utenti dopo una ricalibrazione del catalogo."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostra cosa cambierebbe senza scrivere")
    parser.add_argument("--chat-id", help="Elabora un solo utente")
    parser.add_argument("--limit", type=int, help="Elabora al massimo N utenti")
    args = parser.parse_args()

    store = UserStore(db_url=Config.DATABASE_URL)

    if args.chat_id:
        chat_ids = [args.chat_id]
    else:
        with store.Session() as session:
            chat_ids = [
                row[0] for row in session.query(User.chat_id).filter(
                    User.is_active == True  # noqa: E712
                ).all()
            ]
    if args.limit:
        chat_ids = chat_ids[:args.limit]

    if args.dry_run:
        _preview(store, chat_ids)
        return

    if args.chat_id:
        r = backfill.recompute_xp(store, args.chat_id)
        print(f"[recompute-xp] {r['chat_id']}: {r['old_xp']} -> {r['new_xp']} XP, "
              f"livello {r['old_level']} -> {r['new_level']} ({r['updated']} righe)")
        return

    summary = backfill.recompute_xp_all(store, limit=args.limit)
    for d in summary["level_down"]:
        print(f"  ⚠  {d['chat_id']}: livello {d['old_level']} -> {d['new_level']}")
    print(f"[recompute-xp] Fatto. {summary['users']} utenti, "
          f"{summary['rows_updated']} righe aggiornate, "
          f"{len(summary['level_up'])} saliti, {len(summary['level_down'])} scesi di livello.")
    if summary["unknown_codes"]:
        print(f"[recompute-xp] Codici non più nel registry, XP invariato: "
              f"{', '.join(summary['unknown_codes'])}")


if __name__ == "__main__":
    main()
