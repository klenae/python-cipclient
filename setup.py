import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="python-cipclient",
    version="0.0.1",
    author="Katherine Lenae",
    author_email="klenae@gmail.com",
    description="cip client",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/klenae/python-cipclient",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
    py_modules=["cipclient"],
)