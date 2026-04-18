import boto3
from datetime import datetime
import logging
from botocore.exceptions import ClientError, NoCredentialsError

logger = logging.getLogger(__name__)

class AWSCostMonitor:
    def __init__(self, aws_access_key_id, aws_secret_access_key):
        """Inizializza il monitor dei costi AWS"""
        self.access_key = aws_access_key_id
        self.secret_key = aws_secret_access_key
        
        # Le credenziali vengono configurate solo se disponibili
        if self.access_key and self.secret_key:
            self.ce_client = boto3.client(
                'ce', 
                region_name='us-east-1', # Cost Explorer è us-east-1
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key
            )
        else:
            self.ce_client = None

        # Configurazione istanze da monitorare: tutte in eu-central-1 (Francoforte) come richiesto
        self.monitored_region = 'eu-central-1'
    
    def _get_boto_client(self, service: str, region: str):
        if not self.access_key or not self.secret_key:
            return None
        return boto3.client(
            service,
            region_name=region,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key
        )

    def get_current_month_costs(self):
        """Ottiene i costi del mese corrente raggruppati per servizio e regione"""
        if not self.ce_client:
            return None

        today = datetime.utcnow().date()
        start_date = today.replace(day=1).isoformat()
        end_date = today.isoformat()
        
        if start_date == end_date:
            # Se è il primo del mese, la fine deve essere almeno il giorno dopo esclusivo
            # ma AWS CE richiede Start < End. Se oggi = 1 Oct, chiediamo from 1 Oct to 2 Oct.
            from datetime import timedelta
            end_date = (today + timedelta(days=1)).isoformat()
            
        try:
            response = self.ce_client.get_cost_and_usage(
                TimePeriod={
                    'Start': start_date,
                    'End': end_date
                },
                Granularity='MONTHLY',
                Metrics=['UnblendedCost'],
                GroupBy=[
                    {'Type': 'DIMENSION', 'Key': 'SERVICE'},
                    {'Type': 'DIMENSION', 'Key': 'REGION'}
                ]
            )
            return response
        except Exception as e:
            logger.error(f"Errore nel recupero costi AWS: {e}")
            return None
    
    def get_instance_details(self, region):
        """Ottiene dettagli delle istanze EC2 in una regione"""
        ec2 = self._get_boto_client('ec2', region)
        if not ec2:
            return []
            
        try:
            response = ec2.describe_instances()
            instances = []
            
            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    name = 'N/A'
                    for tag in instance.get('Tags', []):
                        if tag['Key'] == 'Name':
                            name = tag['Value']
                            break
                    
                    instances.append({
                        'InstanceId': instance['InstanceId'],
                        'Name': name,
                        'InstanceType': instance['InstanceType'],
                        'State': instance['State']['Name'],
                        'Region': region
                    })
            return instances
        except Exception as e:
            logger.error(f"Errore recupero istanze EC2 in {region}: {e}")
            return []
    
    def get_rds_details(self, region):
        """Ottiene dettagli dei database RDS in una regione"""
        rds = self._get_boto_client('rds', region)
        if not rds:
            return []
            
        try:
            response = rds.describe_db_instances()
            databases = []
            
            for db in response['DBInstances']:
                databases.append({
                    'DBInstanceIdentifier': db['DBInstanceIdentifier'],
                    'DBInstanceClass': db['DBInstanceClass'],
                    'Engine': db['Engine'],
                    'DBInstanceStatus': db['DBInstanceStatus'],
                    'AllocatedStorage': db['AllocatedStorage'],
                    'StorageType': db['StorageType'],
                    'MultiAZ': db['MultiAZ'],
                    'PubliclyAccessible': db['PubliclyAccessible'],
                    'Region': region
                })
            return databases
        except Exception as e:
            logger.error(f"Errore recupero database RDS in {region}: {e}")
            return []
    
    def generate_dashboard_report(self):
        """Genera report formattato per la dashboard (Flask)"""
        if not self.ce_client:
            return {
                "error": "Credenziali AWS non configurate o invalide",
                "total_cost": 0.0,
                "services": {},
                "ec2": [],
                "rds": []
            }
        
        # Recupera costi grezzi da CE
        cost_data = self.get_current_month_costs()
        
        total_month_cost = 0.0
        service_totals = {}
        
        if cost_data and 'ResultsByTime' in cost_data and len(cost_data['ResultsByTime']) > 0:
            result = cost_data['ResultsByTime'][0]
            for group in result.get('Groups', []):
                cost = float(group['Metrics']['UnblendedCost']['Amount'])
                total_month_cost += cost
                
                service_name = group['Keys'][0]
                if service_name not in service_totals:
                    service_totals[service_name] = 0.0
                service_totals[service_name] += cost
        
        # Ordina per costo decrescente e rimuove quelli a costo 0
        sorted_services = {k: round(v, 4) for k, v in sorted(service_totals.items(), key=lambda item: item[1], reverse=True) if v > 0}
        
        # Recupera le istanze EC2 e RDS scandendo sia Francoforte che Milano (fase di migrazione)
        regions_to_scan = ['eu-central-1', 'eu-south-1']
        ec2_instances = []
        rds_instances = []
        
        for region in regions_to_scan:
            ec2_instances.extend(self.get_instance_details(region))
            rds_instances.extend(self.get_rds_details(region))
        
        return {
            "total_cost": round(total_month_cost, 4),
            "services": sorted_services,
            "ec2": ec2_instances,
            "rds": rds_instances,
            "monitored_region": ', '.join(regions_to_scan)
        }
