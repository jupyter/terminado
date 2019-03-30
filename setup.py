import setuptools
import glob
from terminado import __version__

setuptools.setup(
    name = "terminado",
    version = __version__,
    author = "Jupyter Development Team",
    author_email = "jupyter@googlegroups.com",
    description = "A websocket backend for the Xterm.js JavaScript terminal emulator library.",
    url = "https://github.com/jupyter/terminado",
    packages = setuptools.find_packages(exclude=["doc", "demos", "terminado/_static"]),
    classifiers = [
        "Programming Language :: Python :: 3.7"
    ],
    license = "MIT",
    install_requires=[
        "ptyprocess;os_name!='nt'",
        "pywinpty (>=0.5);os_name=='nt'",
        "tornado (>=4)",
        "python-interface",
        "msgpack"
    ]
)
