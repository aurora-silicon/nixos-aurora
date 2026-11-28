"""boot-splash.nix: the pre-pivot handover service and the display's initrd modules."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / 'modules/boot-splash.nix').read_text()
# CONFIG_PHY_APPLE_* option -> module (drivers/phy/apple/Makefile).
PHY_MODULES = {'ATC': 'phy-apple-atc', 'T6040_USB2': 'phy-apple-t6040-usb2', 'DPTX': 'phy-apple-dptx',
               'T6050_DP': 'atc-t6050-dp'}


class BootSplashHandoverTests(unittest.TestCase):
    def test_the_handover_runs_the_shared_wait_with_its_tools(self):
        # tests/test_early_kms_wait.py covers what the script decides.
        self.assertIn('${builtins.readFile ./aurora-early-kms-wait.sh}', MODULE)
        self.assertIn('PATH=${lib.makeBinPath kmsHandoverTools}', MODULE)
        self.assertIn('kmsHandoverTools = [ config.boot.initrd.systemd.package '
                      'config.boot.initrd.systemd.package.kmod pkgs.coreutils ];', MODULE)
        # The initrd copier does not follow store references inside scripts.
        self.assertIn('[ earlyKms kmsHandover "${config.boot.initrd.systemd.package.kmod}/bin/modprobe" '
                      '"${pkgs.coreutils}/bin/tr" ]', MODULE)
        self.assertNotIn('sleep', MODULE)
        self.assertIn('serviceConfig.ExecStart = kmsHandover;', MODULE)
        # The link the wait names exists only with a by-path rule in the initrd.
        self.assertIn('SYMLINK+="dri/by-path/$env{ID_PATH}-card"', MODULE)

    def test_the_initrd_carries_every_apple_phy_the_kernel_config_builds(self):
        available = re.search(r'boot\.initrd\.availableKernelModules = \[(.*?)\];', MODULE, re.S).group(1)
        available = set(re.findall(r'"([^"]+)"', available))
        config = (ROOT / 'kernel/config').read_text()
        built = re.findall(r'(?m)^CONFIG_PHY_APPLE_(\w+)=m$', config)
        self.assertIn('ATC', built)
        self.assertEqual(re.findall(r'(?m)^CONFIG_PHY_APPLE_\w+=y$', config), [])
        for option in built:
            self.assertIn(PHY_MODULES[option], available, f'CONFIG_PHY_APPLE_{option}=m')
        for module in set(PHY_MODULES.values()) & available:
            option = next(o for o, m in PHY_MODULES.items() if m == module)
            self.assertIn(option, built, f'{module} is not built')


if __name__ == '__main__':
    unittest.main()
