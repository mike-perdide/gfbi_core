SRC_ROOT = gfbi_core
PY = $(wildcard gfbi_core/*.py)
PY_TESTED = $(PY:.py=_py_tested)

test: $(PY_TESTED)

%_py_tested: %.py
	PYTHONPATH=$(SRC_ROOT) python -m doctest $<

install:	test
	python -m "distutils2.run" install||python setup.py install

publish:	test
	python -m "distutils2.run" register sdist upload
