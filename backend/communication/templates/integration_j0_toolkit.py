#!/usr/bin/env python3
"""
Script d'intégration du template J0 avec le toolkit ePerformance.

Usage:
    python integration_j0_toolkit.py --csv prospects_tracking.csv
    python integration_j0_toolkit.py --test  # Mode test (1 email)
    python integration_j0_toolkit.py --dry-run  # Simulation sans envoi

Auteur: ePerformance AI Team
Date: 2026-09-10
"""

import sys
import os
import csv
import json
import asyncio
import random
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

# Ajouter le path du backend au PYTHONPATH
BACKEND_PATH = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_PATH))

try:
    from backend.communication.providers.email_provider import EmailProvider
except ImportError:
    print("⚠️  ERREUR: Impossible d'importer EmailProvider")
    print("   Vérifiez que vous êtes dans le bon environnement virtuel")
    print("   Path attendu:", BACKEND_PATH)
    sys.exit(1)


# Configuration
TEMPLATES_DIR = Path(__file__).parent
CONFIG_PATH = TEMPLATES_DIR / "template_j0_config.json"
HTML_TEMPLATE_PATH = TEMPLATES_DIR / "template_j0_prospect.html"
TXT_TEMPLATE_PATH = TEMPLATES_DIR / "template_j0_prospect.txt"

# Clé API Brevo (à configurer via variable d'environnement)
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")


class J0EmailSender:
    """
    Gestionnaire d'envoi des emails J0 avec le template ePerformance.
    """
    
    def __init__(self, api_key: str, dry_run: bool = False):
        self.dry_run = dry_run
        
        # Charger config
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        # Charger templates
        with open(HTML_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            self.html_template = f.read()
        
        with open(TXT_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            self.txt_template = f.read()
        
        # Initialiser provider (sauf en dry-run)
        if not dry_run and api_key:
            self.email_provider = EmailProvider(
                api_key=api_key,
                sender_email="notifications@eperformance.pro",
                sender_name="Stéphane - ePerformance",
                admin_bcc_email="ballo@eperformance.pro"
            )
        else:
            self.email_provider = None
        
        # Statistiques
        self.stats = {
            "total": 0,
            "sent": 0,
            "failed": 0,
            "skipped": 0
        }
    
    def _choisir_objet_email(self, prenom: Optional[str] = None) -> str:
        """
        Choisir un objet email parmi les 3 variantes (A/B/C).
        Répartition: 40% A, 30% B, 30% C
        """
        variantes = self.config["objets_email"]
        
        # Si prénom disponible, privilégier variantes personnalisées
        if prenom:
            choix = random.choices(
                ["variante_a", "variante_c", "variante_b"],
                weights=[0.40, 0.30, 0.30]
            )[0]
        else:
            # Sans prénom, privilégier variante B (pas de personnalisation)
            choix = random.choices(
                ["variante_b", "variante_a", "variante_c"],
                weights=[0.50, 0.25, 0.25]
            )[0]
        
        objet = variantes[choix]["objet"]
        
        # Remplacer variables
        if prenom:
            objet = objet.replace("{{prenom}}", prenom)
        
        return objet
    
    def _remplacer_variables(self, template: str, variables: Dict[str, str]) -> str:
        """
        Remplacer les variables Brevo dans le template.
        Format: {{ variable }} ou {{ variable | default: 'valeur' }}
        """
        result = template
        
        for key, value in variables.items():
            # Format simple: {{ variable }}
            result = result.replace(f"{{{{ {key} }}}}", value or "")
            
            # Format avec default: {{ variable | default: 'valeur' }}
            # On laisse Brevo gérer les defaults, on remplace juste si valeur existe
            if value:
                result = result.replace(f"{{{{ {key} | default:", f"{{{{ '{value}' | default:")
        
        return result
    
    def _valider_prospect(self, prospect: Dict[str, str]) -> tuple[bool, str]:
        """
        Valider qu'un prospect peut recevoir l'email J0.
        Retourne (valid, raison)
        """
        email = prospect.get("Email", "").strip()
        
        # Email obligatoire
        if not email or "@" not in email:
            return False, "Email invalide ou manquant"
        
        # Vérifier format email basique
        if email.count("@") != 1:
            return False, "Email malformé"
        
        # Vérifier domaines suspects
        domaines_suspects = ["test.com", "example.com", "fake.com"]
        domaine = email.split("@")[1].lower()
        if domaine in domaines_suspects:
            return False, f"Domaine suspect: {domaine}"
        
        # Vérifier si déjà contacté (colonne "Email_J0_Envoye")
        if prospect.get("Email_J0_Envoye", "").lower() == "oui":
            return False, "Email J0 déjà envoyé"
        
        return True, "OK"
    
    def _extraire_prenom(self, prospect: Dict[str, str]) -> str:
        """
        Extraire le prénom du prospect.
        Essaie plusieurs colonnes: Prenom, Nom, Page_Facebook
        """
        # Colonne Prenom directe
        prenom = prospect.get("Prenom", "").strip()
        if prenom:
            return prenom
        
        # Essayer de parser le nom complet
        nom_complet = prospect.get("Nom", "").strip()
        if nom_complet:
            # Prendre le premier mot
            prenom = nom_complet.split()[0]
            if prenom and len(prenom) > 1:
                return prenom
        
        # Fallback: page Facebook
        page_fb = prospect.get("Page_Facebook", "").strip()
        if page_fb:
            # Prendre le premier mot non-vide
            for mot in page_fb.split():
                if len(mot) > 2:
                    return mot
        
        # Dernier fallback
        return "entrepreneur"
    
    async def envoyer_email_j0(self, prospect: Dict[str, str]) -> Dict[str, Any]:
        """
        Envoyer l'email J0 à un prospect.
        """
        self.stats["total"] += 1
        
        # Validation
        valid, raison = self._valider_prospect(prospect)
        if not valid:
            self.stats["skipped"] += 1
            return {
                "success": False,
                "error": raison,
                "prospect": prospect.get("Email", "N/A")
            }
        
        # Extraire données
        email = prospect["Email"].strip()
        prenom = self._extraire_prenom(prospect)
        nom = prospect.get("Nom", prenom).strip()
        entreprise = prospect.get("Page_Facebook", "").strip()
        source = prospect.get("Source", "Scraping").strip()
        
        # Variables pour template
        variables = {
            "prenom": prenom,
            "nom": nom,
            "email": email,
            "entreprise": entreprise,
            "source": source
        }
        
        # Choisir objet email
        objet = self._choisir_objet_email(prenom)
        
        # Préparer contenu HTML et texte
        html_content = self._remplacer_variables(self.html_template, variables)
        txt_content = self._remplacer_variables(self.txt_template, variables)
        
        # Mode dry-run : simuler sans envoyer
        if self.dry_run:
            print(f"\n{'='*70}")
            print(f"📧 DRY-RUN: Email à {email}")
            print(f"{'='*70}")
            print(f"Destinataire: {nom} <{email}>")
            print(f"Objet: {objet}")
            print(f"Variables: {json.dumps(variables, indent=2, ensure_ascii=False)}")
            print(f"{'='*70}\n")
            
            self.stats["sent"] += 1
            return {
                "success": True,
                "message_id": "DRY_RUN",
                "prospect": email
            }
        
        # Envoi réel via Brevo
        if not self.email_provider:
            self.stats["failed"] += 1
            return {
                "success": False,
                "error": "EmailProvider non initialisé (clé API manquante)",
                "prospect": email
            }
        
        try:
            notification = {
                "recipient_email": email,
                "recipient_name": nom,
                "subject": objet,
                "html_content": html_content,
                "text_content": txt_content,
                "tags": self.config["tags_brevo"],
                "reply_to": None,  # Pas de reply-to (redirection WhatsApp)
                "headers": {
                    "X-Campaign": "J0-Prospect",
                    "X-Source": source
                }
            }
            
            result = await self.email_provider.send(notification)
            
            if result["success"]:
                self.stats["sent"] += 1
                print(f"✅ Email envoyé à {email} (ID: {result['message_id']})")
            else:
                self.stats["failed"] += 1
                print(f"❌ Échec envoi à {email}: {result.get('error', 'Erreur inconnue')}")
            
            return result
            
        except Exception as e:
            self.stats["failed"] += 1
            print(f"❌ Exception lors de l'envoi à {email}: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "prospect": email
            }
    
    async def traiter_csv(self, csv_path: str, limit: Optional[int] = None):
        """
        Traiter un CSV de prospects et envoyer les emails J0.
        """
        csv_path = Path(csv_path)
        
        if not csv_path.exists():
            print(f"❌ ERREUR: Fichier CSV introuvable: {csv_path}")
            return
        
        print(f"\n{'='*70}")
        print(f"📊 TRAITEMENT CSV: {csv_path.name}")
        print(f"{'='*70}\n")
        
        # Lire CSV
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            prospects = list(reader)
        
        print(f"📋 {len(prospects)} prospects trouvés dans le CSV")
        
        if limit:
            prospects = prospects[:limit]
            print(f"⚠️  Limite appliquée: {limit} premiers prospects")
        
        # Traiter chaque prospect
        results = []
        for i, prospect in enumerate(prospects, 1):
            print(f"\n[{i}/{len(prospects)}] Traitement: {prospect.get('Email', 'N/A')}")
            
            result = await self.envoyer_email_j0(prospect)
            results.append(result)
            
            # Pause entre envois (rate limiting)
            if not self.dry_run and i < len(prospects):
                await asyncio.sleep(2)  # 2 secondes entre chaque email
        
        # Rapport final
        print(f"\n{'='*70}")
        print(f"📊 RAPPORT FINAL")
        print(f"{'='*70}")
        print(f"Total prospects: {self.stats['total']}")
        print(f"✅ Emails envoyés: {self.stats['sent']}")
        print(f"❌ Échecs: {self.stats['failed']}")
        print(f"⏭️  Ignorés: {self.stats['skipped']}")
        print(f"{'='*70}\n")
        
        # Mettre à jour le CSV avec statut envoi
        if not self.dry_run and self.stats['sent'] > 0:
            self._mettre_a_jour_csv(csv_path, results)
    
    def _mettre_a_jour_csv(self, csv_path: Path, results: List[Dict]):
        """
        Mettre à jour le CSV avec les statuts d'envoi.
        Ajoute colonne "Email_J0_Envoye" et "Email_J0_Date"
        """
        try:
            # Lire CSV original
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                prospects = list(reader)
            
            # Ajouter colonnes si nécessaire
            if "Email_J0_Envoye" not in fieldnames:
                fieldnames.append("Email_J0_Envoye")
            if "Email_J0_Date" not in fieldnames:
                fieldnames.append("Email_J0_Date")
            if "Email_J0_MessageID" not in fieldnames:
                fieldnames.append("Email_J0_MessageID")
            
            # Créer mapping email -> result
            results_map = {r["prospect"]: r for r in results if r.get("prospect")}
            
            # Mettre à jour prospects
            date_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for prospect in prospects:
                email = prospect.get("Email", "").strip()
                if email in results_map:
                    result = results_map[email]
                    if result["success"]:
                        prospect["Email_J0_Envoye"] = "Oui"
                        prospect["Email_J0_Date"] = date_now
                        prospect["Email_J0_MessageID"] = result.get("message_id", "")
            
            # Écrire CSV mis à jour
            backup_path = csv_path.with_suffix('.csv.backup')
            csv_path.rename(backup_path)
            
            with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(prospects)
            
            print(f"✅ CSV mis à jour: {csv_path}")
            print(f"   Backup créé: {backup_path}")
            
        except Exception as e:
            print(f"⚠️  ATTENTION: Impossible de mettre à jour le CSV: {e}")


async def main():
    """Point d'entrée principal"""
    
    parser = argparse.ArgumentParser(
        description="Script d'intégration template J0 avec toolkit ePerformance"
    )
    parser.add_argument(
        "--csv",
        help="Chemin vers le CSV de prospects",
        default=None
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Mode test: envoyer 1 email uniquement"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mode dry-run: simuler sans envoyer"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limiter le nombre d'emails à envoyer",
        default=None
    )
    
    args = parser.parse_args()
    
    # Vérifier clé API (sauf en dry-run)
    if not args.dry_run and not BREVO_API_KEY:
        print("❌ ERREUR: Variable d'environnement BREVO_API_KEY manquante")
        print("   Export: export BREVO_API_KEY='votre_cle_api'")
        sys.exit(1)
    
    # Initialiser sender
    sender = J0EmailSender(api_key=BREVO_API_KEY, dry_run=args.dry_run)
    
    # Déterminer CSV path
    if args.csv:
        csv_path = args.csv
    else:
        # Chercher dans le toolkit
        toolkit_path = Path(__file__).parent.parent.parent.parent.parent / "toolkit_eperformance"
        csv_path = toolkit_path / "prospects_tracking.csv"
    
    # Mode test: limiter à 1
    limit = args.limit
    if args.test:
        limit = 1
        print("🧪 MODE TEST: Envoi d'1 email uniquement\n")
    
    if args.dry_run:
        print("🧪 MODE DRY-RUN: Simulation sans envoi réel\n")
    
    # Traiter CSV
    await sender.traiter_csv(str(csv_path), limit=limit)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interruption utilisateur (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ ERREUR FATALE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
