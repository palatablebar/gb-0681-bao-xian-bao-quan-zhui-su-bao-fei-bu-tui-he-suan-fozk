from app.modules.m2_mapping.rules import normalize
from app.modules.m2_mapping.identity import resolve

def execute(state):
    return resolve(normalize(state))
