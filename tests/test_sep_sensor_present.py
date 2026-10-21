import importlib.machinery
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'sep' / 'sensor-present'
loader = importlib.machinery.SourceFileLoader('sensor_present', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
sensor_present = importlib.util.module_from_spec(spec)
loader.exec_module(sensor_present)


class SensorPresenceTests(unittest.TestCase):
    def probe(self, version, attached):
        def ioctl(fd, request, buffer, mutate):
            self.assertEqual(fd, 9)
            self.assertEqual(request, sensor_present.GET_INFO)
            self.assertTrue(mutate)
            struct.pack_into('=II', buffer, 0, version, attached)

        with patch.object(sensor_present.os, 'open', return_value=9), \
             patch.object(sensor_present.os, 'close') as close, \
             patch.object(sensor_present.fcntl, 'ioctl', side_effect=ioctl):
            result = sensor_present.present('/dev/test-reader')
        close.assert_called_once_with(9)
        return result

    def test_only_current_interface_with_attached_reader_is_enabled(self):
        self.assertTrue(self.probe(4, 1))
        self.assertFalse(self.probe(4, 0))
        self.assertFalse(self.probe(3, 1))

    def test_missing_device_is_not_advertised(self):
        with patch.object(sensor_present.os, 'open', side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                sensor_present.present('/dev/missing')


if __name__ == '__main__':
    unittest.main()
