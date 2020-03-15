"""A setuptools based setup module.

See:
https://packaging.python.org/guides/distributing-packages-using-setuptools/
https://github.com/pypa/sampleproject
"""

# Always prefer setuptools over distutils
from setuptools import setup
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

# Arguments marked as "Required" below must be included for upload to PyPI.
# Fields marked as "Optional" may be commented out.

setup(
    name="python-cipclient",  # Required
    version="0.0.2",  # Required
    description="""A Python-based socket client for communicating
                   with Crestron control processors via CIP.""",  # Optional
    long_description=long_description,  # Optional
    long_description_content_type="text/markdown",  # Required for .md content
    url="https://github.com/klenae/python-cipclient",  # Optional
    author="Katherine Lenae",  # Optional
    author_email="klenae@gmail.com",  # Optional
    classifiers=[  # Optional
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Home Automation",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
    keywords="development cip home-automation",
    python_requires=">=3.6",
    py_modules=["cipclient"],
)
