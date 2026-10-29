from setuptools import setup, find_packages

setup(
    name="movie-explainer",
    version="1.0.0",
    description="Local AI Movie Explanation Studio for Ubuntu Linux",
    author="Movie Explainer Studio Team",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "edge-tts>=7.2.0",
        "pysrt>=1.1.2",
        "webvtt-py>=0.5.1",
        "pyyaml>=6.0.1",
        "pillow>=10.0.0",
        "rich>=13.7.0",
        "click>=8.1.7",
        "psutil>=5.9.0",
        "tqdm>=4.66.0",
        "numpy>=1.24.0",
        "scenedetect>=0.6.4",
        "opencv-python>=4.8.0",
        "faster-whisper>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "movie-explainer=app.main:cli",
        ],
    },
)
