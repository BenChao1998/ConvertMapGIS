# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import glob, os
import shutil

datas = [('resource/*', 'resource'), ('pymapgis.py', '.')]
binaries = []
hiddenimports = ['pyogrio']
tmp_ret = collect_all('pyogrio')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# 收集fiona相关的DLL文件
fiona_imports_paths = glob.glob(r'.venv\Lib\site-packages\fiona.libs\*.dll')

for item in fiona_imports_paths:
    binaries.append((item, '.'))
    # 为gdal.dll创建一个副本以解决依赖问题
    if 'gdal' in item and '303c57f5eade1382c154b3d024282072' in item:
        # 创建gdal.dll的副本
        gdal_copy_path = os.path.join(os.path.dirname(item), 'gdal.dll')
        if not os.path.exists(gdal_copy_path):
            shutil.copy2(item, gdal_copy_path)
        binaries.append((gdal_copy_path, '.'))

# 添加GDAL相关的隐藏导入
hiddenimports += ['fiona', 'fiona._geometry', 'fiona.ogrext', 'osgeo', 'osgeo.gdal', 'osgeo.ogr']

a = Analysis(
    ['main.py'],
    pathex=['.venv/Lib/site-packages'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ConvertMapGIS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['resource\\图标.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ConvertMapGIS',
)
