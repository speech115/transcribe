from setuptools import setup
from wheel.bdist_wheel import bdist_wheel as _bdist_wheel


class bdist_wheel(_bdist_wheel):
    """The vendored executable makes this a macOS arm64 distribution."""

    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False
        self.plat_name = "macosx_11_0_arm64"

    def get_tag(self):
        return "py3", "none", "macosx_11_0_arm64"


setup(cmdclass={"bdist_wheel": bdist_wheel})
