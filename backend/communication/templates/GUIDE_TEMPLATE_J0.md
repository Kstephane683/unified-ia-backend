# 📧 GUIDE D'UTILISATION - TEMPLATE J0 PROSPECT

## 🎯 OBJECTIF DU TEMPLATE

Le template J0 (Jour 0) est conçu pour transformer les nouveaux prospects en conversations WhatsApp qualifiées. Il résout le problème critique des emails sortants uniquement en **redirigeant systématiquement vers WhatsApp** pour toute interaction.

---

## 🚀 QUICK START

### Utilisation avec Brevo (recommandée)

```python
from backend.communication.providers.email_provider import EmailProvider

# Initialiser le provider
email_provider = EmailProvider(
    api_key="votre_cle_api_brevo",
    sender_email="notifications@eperformance.pro",
    sender_name="Stéphane - ePerformance",
    admin_bcc_email="ballo@eperformance.pro"
)

# Préparer la notification
notification = {
    "recipient_email": "prospect@example.com",
    "recipient_name": "Jean Kouadio",
    "subject": "Jean, une surprise pour votre stratégie marketing 🎁",
    "html_content": open("template_j0_prospect.html").read(),
    "text_content": open("template_j0_prospect.txt").read(),
    "template_params": {
        "prenom": "Jean",
        "nom": "Jean Kouadio",
        "email": "prospect@example.com"
    },
    "tags": ["j0_prospect", "first_contact", "diagnostic_gratuit"],
    "reply_to": None  # Pas de reply-to (redirection WhatsApp)
}

# Envoyer
result = await email_provider.send(notification)
```

### Utilisation avec script d'intégration toolkit

```bash
cd /home/ballo/OX6A/unified_ia_system/backend/communication/templates
python integration_j0_toolkit.py --csv /path/to/prospects.csv
```

---

## 📋 VARIABLES BREVO DISPONIBLES

### Variables obligatoires
- `{{ prenom }}` - Prénom du prospect (ex: "Jean")
- `{{ email }}` - Email du prospect

### Variables optionnelles
- `{{ nom }}` - Nom complet du prospect (ex: "Jean Kouadio")
- `{{ entreprise }}` - Nom de l'entreprise du prospect
- `{{ source }}` - Source du prospect (LinkedIn, Facebook, etc.)

### Variables système
- `{{ unsubscribe }}` - Lien de désinscription automatique Brevo

### Exemple de remplacement
```html
<!-- Dans le template HTML -->
<p>Bonjour <span>{{ prenom | default: 'entrepreneur' }}</span> 👋</p>

<!-- Devient après traitement -->
<p>Bonjour <span>Jean</span> 👋</p>
```

---

## 🎨 3 VARIANTES D'OBJET EMAIL (A/B/C)

### Variante A - Personnalisée + Curiosité (Recommandée)
**Objet :** `{{prenom}}, une surprise pour votre stratégie marketing 🎁`
- **Taux d'ouverture cible :** 40%
- **Usage :** Prospects avec prénom connu
- **Psychologie :** Personnalisation + curiosité + émoji cadeau

### Variante B - Valeur + Urgence
**Objet :** `Diagnostic marketing IA offert — Places limitées`
- **Taux d'ouverture cible :** 38%
- **Usage :** Prospects sans prénom ou test alternatif
- **Psychologie :** Valeur directe + urgence + exclusivité

### Variante C - Social Proof + Bénéfice
**Objet :** `{{prenom}}, 29 agents IA pour booster votre business`
- **Taux d'ouverture cible :** 35%
- **Usage :** Prospects tech-savvy ou MLM
- **Psychologie :** Personnalisation + preuve sociale + bénéfice

### Test A/B recommandé
```python
# Répartition 40/30/30
variantes = [
    ("{{prenom}}, une surprise pour votre stratégie marketing 🎁", 0.40),
    ("Diagnostic marketing IA offert — Places limitées", 0.30),
    ("{{prenom}}, 29 agents IA pour booster votre business", 0.30)
]

import random
subject = random.choices([v[0] for v in variantes], weights=[v[1] for v in variantes])[0]
```

---

## 🔗 BOUTONS CTA

### CTA Principal - WhatsApp (Priorité 1)
- **Texte :** "💬 Continuer sur WhatsApp"
- **URL :** `https://wa.me/2250151170666?text=Bonjour%20Stéphane...`
- **Couleur :** #25D366 (vert WhatsApp)
- **Psychologie :** Action immédiate, conversation directe

### CTA Secondaire - Diagnostic (Priorité 2)
- **Texte :** "🎯 Réserver mon diagnostic gratuit"
- **URL :** `https://wa.me/2250151170666?text=Bonjour%2C%20je%20souhaite...`
- **Couleur :** #c9a96e (or ePerformance)
- **Psychologie :** Engagement valeur, lead magnet

### ⚠️ IMPORTANT
- **JAMAIS** de "Répondre à cet email"
- **TOUJOURS** rediriger vers WhatsApp
- **Raison :** Email sortant uniquement, pas de réception

---

## 📊 KPIs CIBLES

| Métrique | Objectif | Tracking |
|----------|----------|----------|
| **Taux d'ouverture** | 35%+ | Brevo automatique |
| **Taux de clic WhatsApp** | 15%+ | Brevo tracking liens |
| **Taux de réservation diagnostic** | 10%+ | Conversations WhatsApp |
| **Taux de réponse email directe** | 0% | ⚠️ Impossible (voulu) |

### Consulter les métriques Brevo

```python
# Via API Brevo
result = await email_provider.get_delivery_status(message_id)

# Statuts possibles :
# - delivered : Email délivré
# - opened : Email ouvert
# - clicked : Lien cliqué (WhatsApp)
# - soft_bounced : Erreur temporaire
# - hard_bounced : Email invalide
```

---

## 🎭 PSYCHOLOGIE DU PROSPECT J0

### Profil type
- **Connaissance :** Ne connaît PAS encore ePerformance
- **Source :** Probablement ajouté via scraping LinkedIn/Facebook
- **Besoins :** Réassurance rapide, solutions concrètes
- **Comportement :** Veut du gratuit avant d'acheter

### Triggers psychologiques utilisés
1. **FOMO (Fear Of Missing Out)** : "Places limitées - 5 diagnostics/semaine"
2. **Social Proof** : "29 agents IA spécialisés"
3. **Autorité** : "Stéphane, Fondateur ePerformance"
4. **Gratuité** : "Diagnostic gratuit (valeur 150€)"
5. **Urgence douce** : "⏰ Attention : Places limitées"

### Parcours décisionnel
```
Email reçu → Objet intrigant → Ouverture
↓
Lecture rapide (15 secondes)
↓
Identification valeur (Diagnostic gratuit)
↓
Décision : Clic WhatsApp OU Ignorer
↓
Si clic → Conversation WhatsApp → Qualification
```

---

## 🛠️ PERSONNALISATION AVANCÉE

### Personnaliser par source du prospect

```python
# Dans integration_j0_toolkit.py
def personnaliser_message(prospect, source):
    if source == "LinkedIn":
        intro = "J'ai vu votre profil LinkedIn et..."
    elif source == "Facebook":
        intro = "J'ai découvert votre page Facebook et..."
    else:
        intro = "Je suis tombé sur votre business et..."
    
    return intro
```

### Personnaliser par secteur d'activité

```python
secteurs = {
    "MLM": "spécialisé en stratégies MLM et parrainage",
    "E-commerce": "expert en automatisation e-commerce",
    "Coaching": "spécialiste marketing pour coachs",
    "Default": "révolutionnant le marketing digital"
}

description = secteurs.get(prospect.secteur, secteurs["Default"])
```

### Personnaliser par timing

```python
import datetime

heure = datetime.datetime.now().hour

if 6 <= heure < 12:
    salutation = "Bonjour"
elif 12 <= heure < 18:
    salutation = "Bon après-midi"
else:
    salutation = "Bonsoir"

# Remplacer dans le template
html = html.replace("Bonjour {{ prenom }}", f"{salutation} {{{{ prenom }}}}")
```

---

## 📱 RESPONSIVE MOBILE

Le template est optimisé pour mobile (70% des ouvertures).

### Breakpoints
- **Desktop** : > 600px
- **Mobile** : ≤ 600px

### Optimisations mobile
- Boutons pleine largeur
- Police adaptative (24px → 16px titres)
- Padding réduit (35px → 25px)
- Icônes visibles et tactiles (44px minimum)

### Test sur devices
```bash
# Preview email sur différents clients
# Utiliser Litmus ou Email on Acid
# Ou envoyer à soi-même et tester sur :
# - Gmail mobile (Android/iOS)
# - Apple Mail (iOS)
# - Outlook mobile
# - Samsung Email
```

---

## ⚠️ BEST PRACTICES & PIÈGES À ÉVITER

### ✅ FAIRE

1. **Toujours rediriger vers WhatsApp**
   - Jamais de "Répondez à cet email"
   - WhatsApp = canal de conversation

2. **Tester avant envoi massif**
   - Envoyer 10-20 emails test
   - Vérifier rendu sur Gmail, Outlook, Apple Mail
   - Valider liens WhatsApp fonctionnels

3. **Respecter les quotas Brevo**
   - Plan gratuit : 300 emails/jour
   - Plan payant : selon abonnement
   - Espacer les envois pour éviter spam

4. **Personnaliser au maximum**
   - Utiliser prénom (taux ouverture +26%)
   - Adapter intro selon source
   - Tester variantes d'objet

5. **Suivre les métriques**
   - Analyser taux d'ouverture hebdomadaire
   - Optimiser objets sous-performants
   - A/B tester continuellement

### ❌ NE PAS FAIRE

1. **Inviter à répondre par email**
   - Email sortant uniquement
   - Prospect frustré si pas de réponse

2. **Surcharger le message**
   - Max 200 mots corps email
   - 3 bénéfices maximum
   - 2 CTA maximum

3. **Utiliser jargon technique**
   - "API", "SDK", "Webhook" → ❌
   - "Automatisation IA", "29 agents" → ✅

4. **Être trop corporate ou casual**
   - Ton : Chaleureux, professionnel, moderne
   - Ni costume-cravate, ni copain de bar

5. **Oublier le mobile**
   - 70% ouvrent sur mobile
   - Tester TOUJOURS sur smartphone

---

## 🔧 TROUBLESHOOTING

### Problème : Email en spam

**Solutions :**
- Authentifier domaine (SPF, DKIM, DMARC)
- Éviter mots spam ("gratuit", "argent", "cliquez ici")
- Ratio texte/image équilibré (60/40)
- Taux de plainte < 0.1%

### Problème : Taux d'ouverture < 20%

**Solutions :**
- Tester autres objets email
- Nettoyer liste (emails invalides)
- Envoyer aux heures optimales (9h-11h, 14h-16h)
- Segmenter audience

### Problème : Clics faibles sur WhatsApp

**Solutions :**
- Rendre CTA plus visible (couleur, taille)
- Ajouter urgence ("Répondez aujourd'hui")
- Simplifier message WhatsApp pré-rempli
- Tester différents textes CTA

### Problème : Variables Brevo non remplacées

**Solutions :**
- Vérifier syntaxe : `{{ prenom }}` (espaces)
- S'assurer que variable existe dans payload
- Utiliser fallback : `{{ prenom | default: 'entrepreneur' }}`
- Logs Brevo pour debug

---

## 📚 RESSOURCES COMPLÉMENTAIRES

### Documentation
- **Brevo API v3** : https://developers.brevo.com/docs
- **Email HTML Best Practices** : https://htmlemailguide.com
- **RGPD & Email Marketing** : https://www.cnil.fr

### Outils utiles
- **Test rendu email** : Litmus, Email on Acid
- **Test spam score** : Mail-Tester.com
- **Validation emails** : ZeroBounce, NeverBounce
- **Générateur objets** : SubjectLine.com

### Support ePerformance
- **WhatsApp** : +225 01 51 17 06 66
- **Email technique** : ballo@eperformance.pro
- **Documentation interne** : Voir fichiers toolkit

---

## 🔄 CHANGELOG

### Version 1.0 (2026-09-10)
- ✨ Création template J0 initial
- ✅ 3 variantes objets A/B/C
- ✅ Redirection WhatsApp systématique
- ✅ Design responsive mobile-first
- ✅ Variables Brevo intégrées
- ✅ Tracking métriques configuré

### Prochaines versions
- [ ] Version SMS J0 (backup email)
- [ ] Séquence J1, J3, J7 (nurturing)
- [ ] Templates sectoriels (MLM, E-commerce, etc.)
- [ ] Vidéo personnalisée dans email
- [ ] Intégration calendrier Calendly

---

## 💡 NOTES FINALES

### Philosophie du template
> "Un email J0 n'est pas une vente, c'est une INVITATION à la conversation. Le vrai travail commence sur WhatsApp."

### Rappel crucial
⚠️ **Ce template résout UN problème spécifique** : l'impossibilité de recevoir des réponses par email. D'où la redirection systématique vers WhatsApp.

### Contact pour questions
Pour toute question sur ce template :
- Slack interne : #toolkit-eperformance
- Email dev : ballo@eperformance.pro
- WhatsApp : +225 01 51 17 06 66

---

**Créé par l'équipe de 5 agents experts ePerformance** 🚀
- Sales-Discovery-Coach (Lead)
- Marketing-Email-Strategist
- Social-Media-Strategist
- Marketing-Growth-Hacker
- Brand-Guardian

**Dernière mise à jour :** 2026-09-10
**Auteur :** Stéphane Ballo & AI Team
**License :** Propriété ePerformance - Usage interne uniquement
