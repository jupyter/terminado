import setuptools

setuptools.setup(
    name="terminado",
    version="0.9.0",
    author="Jupyter Development Team",
    author_email="jupyter@googlegroups.com",
    description="A websocket backend for the Xterm.js JavaScript terminal emulator library.",
    url="https://github.com/jupyter/terminado",
    packages=setuptools.find_packages(exclude=["doc", "demos", "terminado/_static"]),
    classifiers=[
        "Environment :: Web Environment",
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 2.7",
        "Topic :: Terminals :: Terminal Emulators/X Terminals",
    ],
    license="MIT",
    install_requires=[
        "ptyprocess;os_name!='nt'",
        "pywinpty (>=0.5);os_name=='nt'",
        "tornado (>=4)",
        "python-interface",
        "msgpack"
    ]
)
