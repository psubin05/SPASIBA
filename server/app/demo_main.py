"""Local full-flow demo using Suin's real DB and matching services."""
from dataclasses import replace
from .config import Settings
from .main import create_app

app = create_app(replace(Settings.from_env(), simulator_enabled=True, seed_sample_map=True))
