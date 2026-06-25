from setuptools import setup, find_packages

setup(
    name="autoscene-studio",
    version="1.0.0",
    description="Cinematic AI Video Generator — Desktop + CLI",
    author="AutoScene Studio",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "customtkinter>=5.2.0",
        "typer[all]>=0.12.0",
        "pydantic>=2.0.0",
        "python-dotenv>=1.0.0",
        "rich>=13.0.0",
        "pydub>=0.25.1",
        "elevenlabs>=1.0.0",
        "openai>=1.30.0",
        "edge-tts>=6.1.0",
        "aiohttp>=3.9.0",
        "Pillow>=10.0.0",
    ],
    entry_points={
        "console_scripts": [
            "autoscene=app.main:main",
        ],
    },
)
