#!/usr/bin/env python3
"""
Script de test rapide du template J0.
Permet de valider le rendu HTML et l'intégration sans envoyer d'emails.

Usage:
    python test_template_j0.py
"""

import json
from pathlib import Path
from datetime import datetime


def test_chargement_fichiers():
    """Test 1: Vérifier que tous les fichiers sont présents"""
    print("\n" + "="*70)
    print("TEST 1: CHARGEMENT DES FICHIERS")
    print("="*70)
    
    templates_dir = Path(__file__).parent
    fichiers_requis = [
        "template_j0_config.json",
        "template_j0_prospect.html",
        "template_j0_prospect.txt",
        "GUIDE_TEMPLATE_J0.md",
        "integration_j0_toolkit.py",
        "README_MISSION_J0.md"
    ]
    
    tous_presents = True
    for fichier in fichiers_requis:
        chemin = templates_dir / fichier
        if chemin.exists():
            taille = chemin.stat().st_size
            print(f"✅ {fichier:<35} ({taille:>6} bytes)")
        else:
            print(f"❌ {fichier:<35} MANQUANT")
            tous_presents = False
    
    return tous_presents


def test_config_json():
    """Test 2: Valider le JSON de configuration"""
    print("\n" + "="*70)
    print("TEST 2: VALIDATION CONFIG JSON")
    print("="*70)
    
    try:
        config_path = Path(__file__).parent / "template_j0_config.json"
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        print("✅ JSON valide")
        
        # Vérifier sections importantes
        sections = [
            "template_name",
            "variables_brevo",
            "objets_email",
            "cta_buttons",
            "branding",
            "contact",
            "tags_brevo",
            "kpis_cibles"
        ]
        
        for section in sections:
            if section in config:
                print(f"✅ Section '{section}' présente")
            else:
                print(f"❌ Section '{section}' manquante")
                return False
        
        # Vérifier les 3 variantes d'objets
        variantes = ["variante_a", "variante_b", "variante_c"]
        for var in variantes:
            if var in config["objets_email"]:
                objet = config["objets_email"][var]["objet"]
                print(f"✅ {var}: {objet}")
            else:
                print(f"❌ {var} manquante")
                return False
        
        return True
        
    except json.JSONDecodeError as e:
        print(f"❌ ERREUR JSON: {e}")
        return False
    except Exception as e:
        print(f"❌ ERREUR: {e}")
        return False


def test_templates_html():
    """Test 3: Valider les templates HTML et TXT"""
    print("\n" + "="*70)
    print("TEST 3: VALIDATION TEMPLATES HTML/TXT")
    print("="*70)
    
    templates_dir = Path(__file__).parent
    
    # Test HTML
    try:
        html_path = templates_dir / "template_j0_prospect.html"
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Vérifier éléments critiques
        elements = [
            ("DOCTYPE html", "Déclaration DOCTYPE"),
            ("ePerformance", "Branding ePerformance"),
            ("#c9a96e", "Couleur signature or"),
            ("{{ prenom }}", "Variable prenom"),
            ("https://wa.me/2250151170666", "Lien WhatsApp"),
            ("Diagnostic gratuit", "Lead magnet"),
            ("29 agents IA", "Social proof"),
            ("Places limitées", "Urgence"),
            ("@media", "Responsive mobile")
        ]
        
        print("\n📄 Template HTML:")
        tous_presents = True
        for element, description in elements:
            if element in html_content:
                print(f"✅ {description:<30} trouvé")
            else:
                print(f"❌ {description:<30} MANQUANT")
                tous_presents = False
        
        # Test TXT
        txt_path = templates_dir / "template_j0_prospect.txt"
        with open(txt_path, 'r', encoding='utf-8') as f:
            txt_content = f.read()
        
        print("\n📝 Template TXT:")
        elements_txt = [
            ("ePerformance", "Branding"),
            ("{{ prenom }}", "Variable prenom"),
            ("https://wa.me/2250151170666", "Lien WhatsApp"),
            ("DIAGNOSTIC MARKETING GRATUIT", "Lead magnet")
        ]
        
        for element, description in elements_txt:
            if element in txt_content:
                print(f"✅ {description:<30} trouvé")
            else:
                print(f"❌ {description:<30} MANQUANT")
                tous_presents = False
        
        return tous_presents
        
    except Exception as e:
        print(f"❌ ERREUR: {e}")
        return False


def test_variables_brevo():
    """Test 4: Vérifier les variables Brevo"""
    print("\n" + "="*70)
    print("TEST 4: VARIABLES BREVO")
    print("="*70)
    
    templates_dir = Path(__file__).parent
    
    try:
        # Charger template HTML
        html_path = templates_dir / "template_j0_prospect.html"
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Variables attendues
        variables = [
            "{{ prenom }}",
            "{{ prenom | default: 'entrepreneur' }}",
            "{{ unsubscribe }}"
        ]
        
        for var in variables:
            if var in html_content:
                print(f"✅ Variable '{var}' présente")
            else:
                print(f"⚠️  Variable '{var}' non trouvée (peut-être normale)")
        
        # Test remplacement basique
        print("\n🧪 Test remplacement variables:")
        test_vars = {
            "prenom": "Jean",
            "nom": "Jean Kouadio",
            "email": "jean@example.com"
        }
        
        html_test = html_content
        for key, value in test_vars.items():
            html_test = html_test.replace(f"{{{{ {key} }}}}", value)
        
        if "Jean" in html_test and "{{ prenom }}" not in html_test:
            print("✅ Remplacement basique fonctionne")
        else:
            print("⚠️  Remplacement basique problématique")
        
        return True
        
    except Exception as e:
        print(f"❌ ERREUR: {e}")
        return False


def test_integration_script():
    """Test 5: Vérifier le script d'intégration"""
    print("\n" + "="*70)
    print("TEST 5: SCRIPT D'INTÉGRATION")
    print("="*70)
    
    script_path = Path(__file__).parent / "integration_j0_toolkit.py"
    
    try:
        with open(script_path, 'r', encoding='utf-8') as f:
            script_content = f.read()
        
        # Vérifier éléments critiques
        elements = [
            ("class J0EmailSender", "Classe principale"),
            ("def _choisir_objet_email", "Choix objet A/B/C"),
            ("def _remplacer_variables", "Remplacement variables"),
            ("def _valider_prospect", "Validation prospect"),
            ("async def envoyer_email_j0", "Envoi email"),
            ("async def traiter_csv", "Traitement CSV"),
            ("EmailProvider", "Import EmailProvider"),
            ("--dry-run", "Mode dry-run"),
            ("--test", "Mode test")
        ]
        
        tous_presents = True
        for element, description in elements:
            if element in script_content:
                print(f"✅ {description:<30} trouvé")
            else:
                print(f"❌ {description:<30} MANQUANT")
                tous_presents = False
        
        # Vérifier permissions exécution
        import os
        if os.access(script_path, os.X_OK):
            print("✅ Script exécutable (chmod +x)")
        else:
            print("⚠️  Script non exécutable (chmod +x recommandé)")
        
        return tous_presents
        
    except Exception as e:
        print(f"❌ ERREUR: {e}")
        return False


def generer_preview_html():
    """Test 6: Générer preview HTML avec données test"""
    print("\n" + "="*70)
    print("TEST 6: GÉNÉRATION PREVIEW HTML")
    print("="*70)
    
    templates_dir = Path(__file__).parent
    
    try:
        # Charger template
        html_path = templates_dir / "template_j0_prospect.html"
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Données test
        test_data = {
            "prenom": "Jean",
            "nom": "Jean Kouadio",
            "email": "jean.kouadio@example.com",
            "entreprise": "Digital Marketing Pro",
            "unsubscribe": "#unsubscribe"
        }
        
        # Remplacer variables
        html_preview = html_content
        for key, value in test_data.items():
            html_preview = html_preview.replace(f"{{{{ {key} }}}}", value)
            html_preview = html_preview.replace(f"{{{{ {key} | default: 'entrepreneur' }}}}", value)
        
        # Sauvegarder preview
        preview_path = templates_dir / "preview_test_j0.html"
        with open(preview_path, 'w', encoding='utf-8') as f:
            f.write(html_preview)
        
        print(f"✅ Preview généré: {preview_path}")
        print(f"   Ouvrez ce fichier dans un navigateur pour voir le rendu")
        print(f"   Données test utilisées:")
        for key, value in test_data.items():
            print(f"      {key}: {value}")
        
        return True
        
    except Exception as e:
        print(f"❌ ERREUR: {e}")
        return False


def rapport_final(resultats):
    """Afficher le rapport final"""
    print("\n" + "="*70)
    print("RAPPORT FINAL DES TESTS")
    print("="*70)
    
    total = len(resultats)
    reussis = sum(resultats.values())
    
    print(f"\nTests réussis: {reussis}/{total}")
    
    for test_name, success in resultats.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    if reussis == total:
        print("\n🎉 TOUS LES TESTS SONT PASSÉS!")
        print("   Le template J0 est prêt à l'emploi.")
        print("\n📋 Prochaines étapes:")
        print("   1. Configurer BREVO_API_KEY")
        print("   2. Tester en mode dry-run:")
        print("      python integration_j0_toolkit.py --dry-run --csv prospects.csv")
        print("   3. Envoyer 1 email test:")
        print("      python integration_j0_toolkit.py --test --csv prospects.csv")
        print("   4. Ouvrir preview_test_j0.html dans navigateur")
    else:
        print("\n⚠️  CERTAINS TESTS ONT ÉCHOUÉ")
        print("   Vérifiez les erreurs ci-dessus.")
    
    print("\n" + "="*70)


def main():
    """Point d'entrée principal"""
    print("\n" + "="*70)
    print("🧪 TEST SUITE TEMPLATE J0 EPERFORMANCE")
    print("="*70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Répertoire: {Path(__file__).parent}")
    
    # Exécuter tests
    resultats = {
        "Chargement fichiers": test_chargement_fichiers(),
        "Configuration JSON": test_config_json(),
        "Templates HTML/TXT": test_templates_html(),
        "Variables Brevo": test_variables_brevo(),
        "Script intégration": test_integration_script(),
        "Preview HTML": generer_preview_html()
    }
    
    # Rapport final
    rapport_final(resultats)


if __name__ == "__main__":
    main()
