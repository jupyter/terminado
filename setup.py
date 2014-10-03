from distutils.core import setup

with open('README.rst') as f:
    readme = f.read()

setup(name="terminado",
      version='0.1',
      description="Terminals served to term.js using Tornado websockets",
      long_description=readme,
      author='Thomas Kluyver',
      author_email="thomas@kluyver.me.uk",
      url="https://github.com/takluyver/terminado",
      packages=['terminado'],
      package_data={'terminado': ['uimod_embed.js',
                                  '_static/*',
                             ]
                    },
      classifiers=[
          "Environment :: Web Environment",
          "License :: OSI Approved :: BSD License",
          "Programming Language :: Python :: 2",
          "Programming Language :: Python :: 3",
          "Topic :: Terminals :: Terminal Emulators/X Terminals",
         ],
      install_requires=['ptyprocess'],
)