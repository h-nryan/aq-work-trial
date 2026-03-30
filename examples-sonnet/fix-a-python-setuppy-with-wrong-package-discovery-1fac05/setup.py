from setuptools import setup, find_packages
import os

setup(
    name="dataprocessor",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "requests",
    ],
    entry_points={
        "console_scripts": [
            "dataprocessor=src.processor:main",
        ],
    },
    python_requires=">=3.8",
)
