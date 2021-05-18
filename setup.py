from setuptools import setup, find_packages
import io

with io.open('terminado/__init__.py', encoding='utf-8') as fid:
    for line in fid:
        if line.startswith('__version__'):
            version = line.strip().split()[-1][1:-1]
            break


setup_args = dict(
    name = "terminado",
    version = version,
    author = "Jupyter Development Team",
    author_email = "jupyter@googlegroups.com",
    url = "https://github.com/jupyter/terminado",
    packages = find_packages(),
    include_package_data = True,
    description = "Tornado websocket backend for the Xterm.js Javascript terminal emulator library.",
    long_description = open("README.rst").read(),
    long_description_content_type="text/x-rst",
    install_requires = [
        "ptyprocess;os_name!='nt'",
        "pywinpty (>=1.1.0);os_name=='nt'",
        "tornado (>=4)",
    ],
    extras_require = dict(test=['pytest']),
    python_requires=">=3.6",
    classifiers=[
        "Environment :: Web Environment",
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 3",
        "Topic :: Terminals :: Terminal Emulators/X Terminals",
    ]
)


if __name__ == '__main__':
    setup(**setup_args)
