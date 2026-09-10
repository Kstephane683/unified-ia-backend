# ⚡ QUICK START - TEMPLATE J0 EPERFORMANCE

**Template de premier contact optimisé pour convertir prospects → conversations WhatsApp**

---

## 🚀 EN 3 COMMANDES

```bash
# 1. Aller dans le dossier templates
cd /home/ballo/OX6A/unified_ia_system/backend/communication/templates

# 2. Configurer clé API Brevo
export BREVO_API_KEY="votre_cle_api_brevo"

# 3. Tester (simulation sans envoi)
python integration_j0_toolkit.py --csv /path/to/prospects.csv --dry-run
```

---

## 📋 FICHIERS CRÉÉS

| Fichier | Usage |
|---------|-------|
| `template_j0_prospect.html` | Template HTML responsive (20 KB) |
| `template_j0_prospect.txt` | Template texte fallback (3.8 KB) |
| `template_j0_config.json` | Configuration (objets A/B/C, CTA, branding) |
| `integration_j0_toolkit.py` | Script Python d'envoi automatisé |
| `test_template_j0.py` | Suite de tests de validation |
| `GUIDE_TEMPLATE_J0.md` | Documentation complète (12 KB) |
| `README_MISSION_J0.md` | Synthèse mission |
| `RAPPORT_FINAL_J0.md` | Rapport exécutif détaillé |

---

## 🎯 OBJECTIF

**Problème résolu:** Les prospects répondaient par email, mais l'email est sortant uniquement.  
**Solution:** Redirection systématique vers WhatsApp (+225 01 51 17 06 66).

---

## ✨ FONCTIONNALITÉS CLÉS

- ✅ **3 variantes d'objets A/B/C** testables
- ✅ **Design responsive mobile-first** (70% des ouvertures)
- ✅ **2 CTA WhatsApp** ultra-visibles (vert + or)
- ✅ **Lead magnet fort:** Diagnostic gratuit (valeur 150€)
- ✅ **Social proof:** 29 agents IA spécialisés
- ✅ **Urgence douce:** 5 diagnostics/semaine
- ✅ **Automatisation complète** (CSV → Email → Statistiques)

---

## 💻 UTILISATION

### Mode 1: Dry-Run (Simulation)
```bash
python integration_j0_toolkit.py --csv prospects.csv --dry-run
# Affiche ce qui serait envoyé SANS envoyer
```

### Mode 2: Test (1 email)
```bash
python integration_j0_toolkit.py --csv prospects.csv --test
# Envoie 1 seul email pour tester
```

### Mode 3: Production (Massif)
```bash
python integration_j0_toolkit.py --csv prospects.csv --limit 50
# Envoie à 50 premiers prospects du CSV
```

### Mode 4: Preview HTML
```bash
xdg-open preview_test_j0.html
# Ouvre le rendu HTML dans navigateur
```

---

## 📊 CSV REQUIS

Colonnes nécessaires:
- **Email** (obligatoire)
- **Nom** ou **Prenom** (recommandé)
- **Page_Facebook** (optionnel)
- **Source** (optionnel)

Le script ajoute automatiquement:
- `Email_J0_Envoye` (Oui/Non)
- `Email_J0_Date` (timestamp)
- `Email_J0_MessageID` (Brevo ID)

---

## 🎨 3 VARIANTES D'OBJETS

**A (40%):** `{{prenom}}, une surprise pour votre stratégie marketing 🎁`  
**B (30%):** `Diagnostic marketing IA offert — Places limitées`  
**C (30%):** `{{prenom}}, 29 agents IA pour booster votre business`

Le script choisit automatiquement selon disponibilité du prénom.

---

## 🔧 CONFIGURATION

### Variables Brevo
```json
{
  "prenom": "Jean",           // Prénom du prospect
  "nom": "Jean Kouadio",      // Nom complet
  "email": "jean@example.com" // Email
}
```

### Branding ePerformance
- **Couleur signature:** #c9a96e (or)
- **WhatsApp:** +225 01 51 17 06 66
- **Email:** contact@eperformance.pro
- **Site:** https://eperformance.pro

---

## 📈 KPIs CIBLES

| Métrique | Objectif |
|----------|----------|
| **Taux d'ouverture** | 35%+ |
| **Taux de clic WhatsApp** | 15%+ |
| **Taux réservation diagnostic** | 10%+ |
| **Taux réponse email directe** | 0% (voulu) |

---

## ⚠️ IMPORTANT

### ✅ FAIRE
- Tester en dry-run avant production
- Valider emails (format correct)
- Respecter rate limiting (2s entre emails)
- Analyser métriques Brevo

### ❌ NE PAS FAIRE
- Inviter à répondre par email
- Envoyer sans clé API Brevo
- Dépasser 300 emails/jour (plan gratuit)
- Utiliser emails test (test@, fake@, etc.)

---

## 🆘 TROUBLESHOOTING

### Erreur: "BREVO_API_KEY manquante"
```bash
export BREVO_API_KEY="sk-xxx..."
```

### Erreur: "CSV introuvable"
Vérifiez le chemin absolu:
```bash
python integration_j0_toolkit.py --csv /home/ballo/OX6A/toolkit_eperformance/prospects_tracking.csv --dry-run
```

### Erreur: "Import EmailProvider failed"
Activez l'environnement virtuel:
```bash
cd /home/ballo/OX6A/unified_ia_system
source venv/bin/activate
```

### Preview ne s'affiche pas correctement
Ouvrez `preview_test_j0.html` dans Chrome/Firefox (pas de client email).

---

## 📞 SUPPORT

- **WhatsApp:** +225 01 51 17 06 66
- **Email:** ballo@eperformance.pro
- **Doc complète:** GUIDE_TEMPLATE_J0.md (12 KB)

---

## 🎯 CHECKLIST AVANT ENVOI

- [ ] Clé API Brevo configurée
- [ ] CSV prospects validé (colonne Email présente)
- [ ] Test en dry-run effectué
- [ ] 1 email test envoyé et vérifié
- [ ] Rendu vérifié sur Gmail mobile
- [ ] Statistiques Brevo configurées
- [ ] Rate limiting respecté (2s)

---

## 🚀 COMMANDE ULTIME

```bash
# Configuration + Test + Production en une fois
export BREVO_API_KEY="votre_cle" && \
cd /home/ballo/OX6A/unified_ia_system/backend/communication/templates && \
python integration_j0_toolkit.py \
  --csv /home/ballo/OX6A/toolkit_eperformance/prospects_tracking.csv \
  --limit 10
```

---

**🎉 TEMPLATE J0 PARFAIT - PRÊT À CONVERTIR! 🚀**

**Créé par:** 5 agents experts ePerformance  
**Date:** 2026-09-10  
**Version:** 1.0
