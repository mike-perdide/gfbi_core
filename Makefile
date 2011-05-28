SRC_ROOT = gfbi_core
PY = $(wildcard gfbi_core/*.py)
PY_TESTED = $(PY:.py=_py_tested)

test: $(PY_TESTED)

%_py_tested: %.py
	PYTHONPATH=$(SRC_ROOT) python -m doctest $<

install:	test
	pysetup run install_dist||python setup.py install

publish:	test
	pysetup run register sdist upload
