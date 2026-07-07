import os
from codebase_to_text import CodebaseToText

# Configuration
input_dir = "."
output_file = "project_codebase.txt"

# Liste des dossiers à inclure (recursif par défaut avec codebase_to_text)
# Si vous voulez restreindre, assurez-vous que ces dossiers existent.
include_paths = [
    "backend/api",
    "backend/core",
    "backend/data",
    "backend/ml",
    "backend/simulation",
    "frontend/src"
]

# Exclusion ciblée uniquement sur les fichiers non-code
# On supprime les exclusions trop larges comme '**/.*'
exclude_patterns = [
    "**/__pycache__/**",
    "**/*.db",
    "**/*.hdf5",
    "**/*.h5",
    "**/*.md",
    "**/vectorbtpro_package/**"
]

def run_conversion():
    # Note : Si codebase-to-text ne respecte pas nativement une liste 'include',
    # nous passons par une liste d'exclusion qui laisse passer le code.
    converter = CodebaseToText(
        input_path=input_dir,
        output_path=output_file,
        output_type="txt",
        exclude=exclude_patterns,
        verbose=True
    )
    
    converter.get_file()
    print(f"Export terminé : {output_file}")

if __name__ == "__main__":
    run_conversion()