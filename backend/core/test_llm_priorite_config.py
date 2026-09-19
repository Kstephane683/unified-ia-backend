# -*- coding: utf-8 -*-
"""Priorité de résolution de la configuration LLM — non-régression.

Contexte : la refonte du toolkit prévoit de purger `config_ia.json`. Avec
l'ordre inverse (fichier d'abord), ce fichier présent mais **sans clé
exploitable** était retourné sans condition : le backend démarrait alors sans
aucune clé, sans erreur et sans trace. Ces tests verrouillent l'ordre correct
et, surtout, l'impossibilité de court-circuiter l'environnement en silence.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.llm_client import LLMClient  # noqa: E402


def client_sans_init():
    """Instance sans passer par le constructeur : on teste _load_config seule."""
    return LLMClient.__new__(LLMClient)


def ecrire(contenu: str) -> str:
    fichier = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    fichier.write(contenu)
    fichier.close()
    return fichier.name


def test_environnement_prioritaire_sur_le_fichier():
    """Une clé d'environnement l'emporte sur le fichier : c'est l'ordre voulu."""
    chemin = ecrire(json.dumps({"api_keys": {"deepseek": "cle-du-fichier"}}))
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "cle-environnement"}, clear=False):
        config = client_sans_init()._load_config(chemin)
    assert config["api_keys"]["deepseek"] == "cle-environnement"
    os.unlink(chemin)


def test_fichier_vide_ne_court_circuite_pas_lenvironnement():
    """LE défaut d'origine : `{}` renvoyé tel quel coupait toutes les clés."""
    chemin = ecrire("{}")
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "cle-environnement"}, clear=False):
        config = client_sans_init()._load_config(chemin)
    assert config["api_keys"]["deepseek"] == "cle-environnement", (
        "un config_ia.json vide a court-circuité l'environnement"
    )
    os.unlink(chemin)


def test_fichier_sans_cle_est_ignore():
    """Un fichier bien formé mais dépourvu de clé ne vaut pas mieux qu'un vide."""
    chemin = ecrire(json.dumps({"api_keys": {"deepseek": "", "openai": ""},
                                "commentaire": "purgé"}))
    with patch.dict(os.environ, {"CLAUDE_GATEWAY_KEY": "cle-passerelle"}, clear=False):
        config = client_sans_init()._load_config(chemin)
    assert config["claude_gateway"]["api_key"] == "cle-passerelle"
    os.unlink(chemin)


def test_fichier_utilise_quand_lenvironnement_est_absent():
    """Le repli fichier doit continuer de fonctionner : c'est le développement local."""
    chemin = ecrire(json.dumps({"api_keys": {"deepseek": "cle-du-fichier"}}))
    sans_cles = {k: "" for k in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "CLAUDE_GATEWAY_KEY")}
    with patch.dict(os.environ, sans_cles, clear=False):
        config = client_sans_init()._load_config(chemin)
    assert config["api_keys"]["deepseek"] == "cle-du-fichier"
    os.unlink(chemin)


def test_fichier_illisible_tombe_sur_lenvironnement():
    """Un JSON cassé ne doit pas empêcher la production de démarrer."""
    chemin = ecrire("{ceci n'est pas du json")
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "cle-environnement"}, clear=False):
        config = client_sans_init()._load_config(chemin)
    assert config["api_keys"]["deepseek"] == "cle-environnement"
    os.unlink(chemin)


def test_aucune_cle_nulle_part_rend_une_configuration_vide():
    """Dernier cas : ni environnement ni fichier. On doit le DIRE, pas planter."""
    sans_cles = {k: "" for k in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "CLAUDE_GATEWAY_KEY")}
    with patch.dict(os.environ, sans_cles, clear=False):
        config = client_sans_init()._load_config("/chemin/inexistant.json")
    assert config == {}


def test_chemin_inexistant_ne_leve_pas():
    """Un chemin explicite introuvable est traité comme une absence, pas une erreur."""
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "cle-environnement"}, clear=False):
        assert client_sans_init()._load_config("/nulle/part.json") != {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
