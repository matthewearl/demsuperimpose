from setuptools import setup

setup(
    name='demsuperimpose',
    description='Quake demo superimposer',
    url='https://github.com/matthewearl/demsuperimpose',
    author='Matthew Earl',
    packages=['demsuperimpose'],
    install_requires=[],
    entry_points={
        'console_scripts': [
            'demsuperimpose = demsuperimpose.demsuperimpose:demsuperimpose_main'
        ]
    },
)
