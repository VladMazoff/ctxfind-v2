
from setuptools import setup, find_packages

setup(
    name="ctxfind-v2",
    version="2.0.0-alpha",
    description="Context-aware code search — AST edition",
    packages=find_packages(),
    install_requires=[
        "pathspec>=0.11.0",
    ],
    extras_require={
        "ast": [
 "tree-sitter==0.20.4; python_version >= '3.8'",
"tree-sitter-languages==1.10.2; python_version >= '3.8'"
        ],
    },
    entry_points={
        "console_scripts": [
            "ctxfind=cli:main",
        ],
    },
    python_requires=">=3.8",
)
