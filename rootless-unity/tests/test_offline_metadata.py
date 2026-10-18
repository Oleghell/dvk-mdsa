from pathlib import Path
import struct
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from offline_metadata import Metadata31,MetadataError


def fixture():
    strings=b'\0Fixture.dll\0Fixture\0Example\0get_Value\0'
    si=lambda name:strings.index(name.encode()+b'\0')
    h=[0]*64;h[:2]=[0xFAB11BAF,31]
    h[6:8]=[256,len(strings)]
    mo=256+len(strings);h[12:14]=[mo,36]
    to=mo+36;h[40:42]=[to,88]
    io=to+88;h[42:44]=[io,40]
    method=struct.pack('<IiiiiiI4H',si('get_Value'),0,0,0,0,-1,0x06000001,0x10,0,0,0)
    t=[0]*26;t[0]=si('Example');t[1]=si('Fixture');t[9]=0;t[16]=1
    typ=struct.pack('<II14i8HII',*t)
    image=struct.pack('<IiiIiIiIiI',si('Fixture.dll'),0,0,1,-1,0,-1,1,0,0)
    return struct.pack('<64I',*h)+strings+method+typ+image


TYPES=[('Fixture.Example','Fixture.dll','Fixture','Example')]
METHODS=[('Fixture.Example','get_Value',0)]


class Offline(unittest.TestCase):
    def test_valid_ownership_and_static_flag(self):
        v=Metadata31(fixture()).check_catalog(TYPES,METHODS)
        self.assertTrue(v['catalog_complete']);self.assertEqual(v['image_count'],1)
        self.assertTrue(v['method_static']['Fixture.Example.get_Value/0'])
    def test_missing_type_and_method_not_guessed(self):
        v=Metadata31(fixture()).check_catalog([('Other','Other.dll','','Missing')],[('Other','get_Value',0)])
        self.assertFalse(v['catalog_complete']);self.assertIsNone(v['method_static']['Other.get_Value/0'])
    def test_arity_must_match(self):
        v=Metadata31(fixture()).check_catalog(TYPES,[('Fixture.Example','get_Value',1)])
        self.assertFalse(v['catalog_complete'])
    def test_version_magic_and_short_input(self):
        for data in (b'',b'0'*256,fixture()[:4]+struct.pack('<I',29)+fixture()[8:]):
            with self.assertRaises(MetadataError):Metadata31(data)
    def test_section_out_of_bounds_or_misaligned(self):
        for offset,size in ((0,36),(0xffffffff,36),(256,0xffffffff),(256,35)):
            data=bytearray(fixture());struct.pack_into('<II',data,12*4,offset,size)
            with self.assertRaises(MetadataError):Metadata31(bytes(data))
    def test_overlapping_sections(self):
        data=bytearray(fixture());struct.pack_into('<II',data,12*4,256,36)
        with self.assertRaises(MetadataError):Metadata31(bytes(data))
    def test_type_owner_range(self):
        data=bytearray(fixture());io=struct.unpack_from('<I',data,42*4)[0];struct.pack_into('<i',data,io+8,3)
        with self.assertRaises(MetadataError):Metadata31(bytes(data))
    def test_method_declaring_type(self):
        data=bytearray(fixture());mo=struct.unpack_from('<I',data,12*4)[0];struct.pack_into('<i',data,mo+4,99)
        with self.assertRaises(MetadataError):Metadata31(bytes(data))
    def test_invalid_string_index(self):
        data=bytearray(fixture());mo=struct.unpack_from('<I',data,12*4)[0];struct.pack_into('<I',data,mo,0xffffffff)
        with self.assertRaises(MetadataError):Metadata31(bytes(data))
    def test_invalid_utf8(self):
        data=bytearray(fixture());data[257]=0xff
        with self.assertRaises(MetadataError):Metadata31(bytes(data))
    def test_output_only_requested_names(self):
        v=Metadata31(fixture()).check_catalog([],[])
        self.assertEqual(v['known_types'],{});self.assertNotIn('Fixture.dll',str(v))
    def test_file_load(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'metadata.dat';p.write_bytes(fixture())
            self.assertEqual(len(Metadata31.load(p).images),1)


if __name__=='__main__':unittest.main()
