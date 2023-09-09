General Jupyter contributor guidelines
======================================

If you're reading this section, you're probably interested in contributing to
Jupyter.  Welcome and thanks for your interest in contributing!

Please take a look at the Contributor documentation, familiarize yourself with
using the ``terminado``, and introduce yourself on the mailing list and
share what area of the project you are interested in working on.

For general documentation about contributing to Jupyter projects, see the
`Project Jupyter Contributor Documentation`__.

__ https://jupyter.readthedocs.io/en/latest/contributing/content-contributor.html

Setting Up a Development Environment
====================================

Installing Terminado
--------------------

Run the the following steps to set up a local development environment::

    pip install --upgrade setuptools pip
    git clone https://github.com/jupyter/terminado
    cd terminado
    pip install -e ".[test]"

If you are using a system-wide Python installation and you only want to installed for you,
you can add ``--user`` to the install commands.


Code Styling
-----------------------------
``terminado`` has adopted automatic code formatting so you shouldn't
need to worry too much about your code style.
As long as your code is valid,
the pre-commit hook should take care of how it should look.
``pre-commit`` and its associated hooks will automatically be installed when
you run ``pip install -e ".[test]"``

To install ``pre-commit`` manually, run the following::

    pip install pre-commit
    pre-commit install


You can invoke the pre-commit hook by hand at any time with::

    pre-commit run

which should run any autoformatting on your code
and tell you about any errors it couldn't fix automatically.
You may also install [black integration](https://github.com/psf/black#editor-integration)
into your text editor to format code automatically.

If you have already committed files before setting up the pre-commit
hook with ``pre-commit install``, you can fix everything up using
``pre-commit run --all-files``. You need to make the fixing commit
yourself after that.


Running Tests
=============

Install dependencies::

    pip install -e .[test]

To run the Python tests, use::

    pytest


Building the Docs
=================

To build the docs, run the following::

    cd doc
    pip install -r requirements.txt
    make html

.. _conda environment:
    https://conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html#creating-an-environment-from-an-environment-yml-file


After that, the generated HTML files will be available at
``build/html/index.html``. You may view the docs in your browser.

You can automatically check if all hyperlinks are still valid::

    make linkcheck

Windows users can find ``make.bat`` in the ``docs`` folder.

You should also have a look at the `Project Jupyter Documentation Guide`__.

__ https://jupyter.readthedocs.io/en/latest/contributing/content-contributor.html
