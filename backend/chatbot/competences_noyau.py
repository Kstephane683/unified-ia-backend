"""
Compétences sectorielles de Mia — SNAPSHOT GÉNÉRÉ, NE PAS ÉDITER.

Source : agent-ia-web/eperf_core/sectors.py (sha256:0cdbd3bcf725fb98).
Régénérer par : python3 scripts/generer_competences_noyau.py

POURQUOI UN SNAPSHOT ET PAS UN IMPORT
-------------------------------------
Le noyau (agent-ia-web) n'est pas déployé sur Railway : importer
`sectors.py` au runtime planterait la production. Ce fichier est la
copie versionnée des données de référence (contenu PUBLIC du noyau :
nom du secteur, intention, thèmes FAQ, item). Le noyau reste la source
de vérité : toute évolution passe par lui, puis par une régénération.

Ces données alimentent GET /api/client/v1/sites/{site_id}/competences
(écran 8 de l'app Mia : ce que Mia sait faire dans le métier du site).
"""

from __future__ import annotations

SECTEURS_CORE: dict[str, dict] = {
    'artisan': {
        "nom": 'Artisanat et bâtiment',
        "intention": "Obtenir un devis : montrer les prestations, les chantiers déjà livrés, et l'atelier ou l'équipe qui les tient.",
        "faq_themes": (
            'devis',
            'délais et planning',
            'matériaux et finitions',
            "zone d'intervention",
        ),
        "item": {
            "nom": 'Prestation',
            "nom_pluriel": 'Prestations',
            "unite": '',
        },
    },
    'beaute': {
        "nom": 'Beauté et soins',
        "intention": "Vendre des soins à l'acte (coiffure, esthétique, spa) : le site doit montrer la main qui tient le geste et le résultat obtenu, puis prendre rendez-vous.",
        "faq_themes": (
            'soins',
            'prise de rendez-vous',
            'produits utilisés',
            'annulation et report',
        ),
        "item": {
            "nom": 'Soin',
            "nom_pluriel": 'Soins',
            "unite": 'la séance',
        },
    },
    'blog': {
        "nom": 'Blog',
        "intention": "Installer une voix et la faire lire régulièrement : la liste des articles en accueil, l'auteur en second, l'abonnement en sortie.",
        "faq_themes": (
            'contact éditorial',
            'partenariats et contributions',
            'droit de citation',
            'newsletter',
        ),
        "item": None,
    },
    'ecommerce': {
        "nom": 'Boutique en ligne',
        "intention": 'Faire commander : montrer le catalogue avec les prix, les conditions de livraison et de retour, et lever les objections avant le panier.',
        "faq_themes": (
            'livraison',
            'retours et remboursements',
            'paiement',
            'compte client',
        ),
        "item": {
            "nom": 'Produit',
            "nom_pluriel": 'Produits',
            "unite": '',
        },
    },
    'education': {
        "nom": 'Éducation et formation',
        "intention": "Faire candidater : présenter les programmes et leurs frais, la pédagogie qui les distingue, et les preuves d'insertion.",
        "faq_themes": (
            'inscription et dossier',
            'frais de scolarité',
            'diplômes et accréditations',
            'calendrier et rythme',
        ),
        "item": {
            "nom": 'Formation',
            "nom_pluriel": 'Formations',
            "unite": '',
        },
    },
    'email': {
        "nom": "Gabarits d'e-mail",
        "intention": "Outiller une séquence d'e-mails transactionnels et de campagne : quatre gabarits autonomes (bienvenue, relance, offre, confirmation) et pas un site.",
        "faq_themes": (
            'désinscription',
            'fréquence des envois',
            'données personnelles',
            "répondre à l'expéditeur",
        ),
        "item": None,
    },
    'evenementiel': {
        "nom": 'Événementiel',
        "intention": 'Remplir une date : publier le programme, ouvrir la billetterie ou la réservation, et montrer les éditions passées.',
        "faq_themes": (
            'billetterie et places',
            'devis',
            'lieu et accès',
            'prestataires et traiteurs',
        ),
        "item": {
            "nom": 'Événement',
            "nom_pluriel": 'Événements',
            "unite": 'la place',
        },
    },
    'hotellerie': {
        "nom": 'Hôtellerie',
        "intention": "Faire réserver une nuit : montrer les chambres avec leur tarif, les offres de séjour, et rassurer par les avis et l'accès.",
        "faq_themes": (
            'arrivée et départ',
            'réservation et annulation',
            'équipements',
            'accès et stationnement',
        ),
        "item": {
            "nom": 'Chambre',
            "nom_pluriel": 'Chambres',
            "unite": 'la nuit',
        },
    },
    'immobilier': {
        "nom": 'Immobilier',
        "intention": "Faire visiter : présenter les biens disponibles, situer l'intervention, et donner un interlocuteur identifié.",
        "faq_themes": (
            'visite',
            'financement',
            'frais et notaire',
            'estimation',
        ),
        "item": {
            "nom": 'Bien',
            "nom_pluriel": 'Biens',
            "unite": '',
        },
    },
    'mlm': {
        "nom": 'Marketing de réseau',
        "intention": "Faire rejoindre un réseau : expliquer comment on démarre, ce que rapporte chaque niveau, et qui l'a déjà fait — sans promesse de revenu.",
        "faq_themes": (
            'démarrage et investissement',
            'plan de rémunération',
            'produits',
            'parrainage et parrain',
        ),
        "item": {
            "nom": 'Produit',
            "nom_pluriel": 'Produits',
            "unite": '',
        },
    },
    'restauration': {
        "nom": 'Restauration',
        "intention": 'Donner faim et lever le doute pratique : la carte, les formules, les horaires et un moyen de réserver une table.',
        "faq_themes": (
            'réservation',
            'allergies et régimes',
            'horaires',
            'groupes et événements privés',
        ),
        "item": {
            "nom": 'Plat',
            "nom_pluriel": 'Plats',
            "unite": '',
        },
    },
    'sante': {
        "nom": 'Santé',
        "intention": 'Convertir une inquiétude en rendez-vous : dire qui soigne, selon quelle méthode, et à quel tarif — sans promettre de résultat.',
        "faq_themes": (
            'prise de rendez-vous',
            'remboursement et mutuelle',
            'assurance',
            'urgences',
        ),
        "item": {
            "nom": 'Soin',
            "nom_pluriel": 'Soins',
            "unite": 'la consultation',
        },
    },
    'tourisme': {
        "nom": 'Tourisme et voyages',
        "intention": "Faire partir : présenter des séjours et des circuits datés, les destinations couvertes, et donner envie par l'image.",
        "faq_themes": (
            'devis et réservation',
            'formalités et visa',
            'annulation',
            'taille des groupes',
        ),
        "item": {
            "nom": 'Séjour',
            "nom_pluriel": 'Séjours',
            "unite": 'la personne',
        },
    },
    'vitrine': {
        "nom": 'Site vitrine',
        "intention": "Présenter une activité de service qui se vend au contact, pas au panier : la page d'accueil doit surtout prouver qu'on existe et que le travail est réel, puis amener au formulaire de contact.",
        "faq_themes": (
            "déroulement d'une prestation",
            'devis',
            'délais',
            "zone d'intervention",
        ),
        "item": None,
    },
}
