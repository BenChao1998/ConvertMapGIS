import datetime
import re
import struct

import geopandas as gpd
import numpy as np
import pandas as pd
import pypinyin
import shapely
from pyproj import CRS


class MapGisReader:
    """
    MapGIS 文件读取器，支持点、线、面要素的解析与转换。
    """
    def __init__(self, filepath, scale_factor=None, wkid=None):
        self.element_count = 0
        self.wkid = wkid
        self.coordinate_scale = scale_factor if scale_factor is not None else None
        self.filepath = filepath
        self.file = open(filepath, 'rb')
        self.shape_type = self._detect_shape_type()
        self._read_headers()
        self._parse_feature_data()
        self._build_geodataframe()

    def _detect_shape_type(self):
        """检测文件类型并返回要素类型。"""
        type_dict = {'WMAP`D22': 'POINT', 'WMAP`D23': 'POLYGON', 'WMAP`D21': 'LINE'}
        file_type = self.file.read(8).decode('gbk')
        if file_type not in type_dict:
            raise InvalidFileError()
        self.file.read(4)  # 跳过无用字节
        return type_dict[file_type]

    def _read_headers(self):
        """读取数据区头部信息。"""
        data_start = struct.unpack('1i', self.file.read(4))[0]
        self.file.seek(data_start)
        self.headers = [self.file.read(10) for _ in range(10)]

    def _parse_feature_data(self):
        """根据要素类型解析属性和几何数据。"""
        if self.shape_type == 'POINT':
            start, _ = struct.unpack('2i', self.headers[2][:-2])
            self._parse_attributes(start)
            self._parse_points()
        elif self.shape_type == 'LINE':
            start, _ = struct.unpack('2i', self.headers[2][:-2])
            self._parse_attributes(start)
            self._parse_lines()
        elif self.shape_type == 'POLYGON':
            start, _ = struct.unpack('2i', self.headers[9][:-2])
            self._parse_attributes(start)
            self._parse_polygons()

    def _parse_attributes(self, start):
        """解析属性表。"""
        self.file.seek(start)
        self.file.read(2)
        self.file.read(4)  # 创建日期
        self.file.read(6)
        attr_offset = struct.unpack('1i', self.file.read(4))[0]
        self.file.read(4)
        self.file.read(4)
        self.file.read(128)  # 工作目录路径
        self.file.read(128)
        self.file.read(40)
        self.file.read(2)
        field_count = struct.unpack('1h', self.file.read(2))[0]
        record_count = struct.unpack('1i', self.file.read(4))[0]
        record_length = struct.unpack('1h', self.file.read(2))[0]
        self.file.read(18)
        field_names, field_types, field_offsets, field_lengths = [], [], [], []
        for _ in range(field_count):
            raw = self.file.read(20)
            try:
                name = raw.decode('gbk').strip('\x00')
            except UnicodeDecodeError as err:
                name = raw[:int(re.search(r'in position (\d+)', str(err)).group(1))].decode('gbk')
            field_names.append(name)
            field_types.append(ord(self.file.read(1)))
            field_offsets.append(struct.unpack('1i', self.file.read(4))[0])
            self.file.read(2)
            field_lengths.append(struct.unpack('1h', self.file.read(2))[0])
            self.file.read(1)
            self.file.read(1)
            self.file.read(2)
            self.file.read(2)  # 跳过记录数
            self.file.read(4)
        # 过滤有效字段
        valid_types = {0, 1, 2, 3, 4, 5, 6, 7}
        mask = [t in valid_types for t in field_types]
        field_names = np.array(field_names)[mask]
        type_dict = {0: 'string', 1: 'byte', 2: 'short', 3: 'int', 4: 'float', 5: 'double', 6: 'date', 7: 'time'}
        field_types = np.array(field_types)[mask]
        field_offsets = np.array(field_offsets)[mask]
        field_lengths = np.array(field_lengths)[mask]
        # 计算每个字段的实际长度
        offsets = list(field_offsets) + [record_length]
        field_actual_lengths = [offsets[i+1] - offsets[i] for i in range(len(field_offsets))]
        self.fields = list(zip(field_names, [type_dict[t] for t in field_types], field_actual_lengths))
        self.file.read(record_length)
        # 优化：一次性读取所有属性数据，减少 file.read 调用次数
        all_attr_bytes = self.file.read(record_length * (record_count - 1))
        data = []
        for i in range(record_count - 1):
            row = all_attr_bytes[i * record_length: (i + 1) * record_length]
            attr = []
            for j in range(len(field_offsets)):
                start_idx = field_offsets[j]
                end_idx = field_offsets[j+1] if j < len(field_offsets) - 1 else None
                value = row[start_idx:end_idx]
                t = field_types[j]
                if t == 4:
                    attr.append(struct.unpack('1f', value)[0])
                elif t == 3:
                    attr.append(struct.unpack('1i', value)[0])
                elif t == 2:
                    attr.append(struct.unpack('1h', value)[0])
                elif t == 1:
                    attr.append(ord(value))
                elif t == 5:
                    attr.append(struct.unpack('1d', value)[0])
                elif t == 6:
                    temp = value
                    attr.append(datetime.date(struct.unpack('1h', temp[:2])[0], temp[2], temp[3]))
                elif t == 7:
                    temp = value
                    attr.append(datetime.time(temp[0], temp[1], *self._parse_time_fraction(struct.unpack('1d', temp[2:])[0])))
                elif t == 0:
                    try:
                        attr.append(value.decode('gbk').strip('\x00'))
                    except UnicodeDecodeError as err:
                        m = re.search(r'in position (\\d+)', str(err))
                        if m:
                            attr.append(value[:int(m.group(1))].decode('gbk'))
                        else:
                            attr.append(value.decode('gbk', errors='replace').strip('\x00'))
            data.append(attr)
        self.data = pd.DataFrame(data, columns=field_names)
        # 合并更多信息
        more_info = self._parse_more_info()
        self.data = pd.concat([self.data, more_info], axis=1)
        # 字段名去重
        self.data.columns = self._deduplicate_columns(self.data.columns)
        self.res_head = self.data.columns.tolist()

    def _parse_time_fraction(self, value):
        """解析小数部分为微秒。"""
        int_part = int(np.floor(value))
        micro = int(1000000 * (value - np.floor(value)))
        return int_part, micro

    def _deduplicate_columns(self, columns):
        """字段名去重。"""
        seen = set()
        result = []
        for col in columns:
            if col not in seen:
                result.append(col)
                seen.add(col)
            else:
                idx = 1
                new_col = f"{col}-{idx}"
                while new_col in seen:
                    idx += 1
                    new_col = f"{col}-{idx}"
                result.append(new_col)
                seen.add(new_col)
        return result

    def _parse_more_info(self):
        """根据类型解析更多要素信息。"""
        self.file.seek(0)
        type_dict = {'WMAP`D22': 'POINT', 'WMAP`D23': 'POLYGON', 'WMAP`D21': 'LINE'}
        file_type = self.file.read(8).decode('gbk')
        if file_type not in type_dict:
            raise InvalidFileError()
        self.file.read(4)
        data_start = struct.unpack('1i', self.file.read(4))[0]
        self.file.seek(data_start)
        headers = [self.file.read(10) for _ in range(10)]
        if file_type == 'WMAP`D22':
            return self._parse_point_info(headers)
        elif file_type == 'WMAP`D21':
            return self._parse_line_info(headers)
        elif file_type == 'WMAP`D23':
            return self._parse_polygon_info(headers)

    def _parse_point_info(self, headers):
        """解析点要素详细信息。"""
        start, vol = struct.unpack('2i', headers[0][:-2])
        columns = ["ID", '坐标X', "坐标Y", "点类型", "透明输出", "颜色", "字符串", "字符高度", "字符宽度", "字符间隔", "字符串角度", "中文字体", "西文字体", "字形", "排列", "子图号", "子图高", "子图宽", "子图角度", "子图线宽", "子图辅色", "圆半径", "圆轮廓颜色", "圆笔宽", "圆填充", "弧半径", "弧起始角度", "弧终止角度", "弧笔宽"]
        df = pd.DataFrame(columns=columns)
        for i in range(int(vol / 93) - 1):
            df.loc[i, 'ID'] = i
            self.file.seek(start + 93 * (i + 1))
            self.file.read(1)
            str_count = struct.unpack('1h', self.file.read(2))[0]
            char_offset = struct.unpack('1i', self.file.read(4))[0]
            x, y = struct.unpack('2d', self.file.read(16))
            df.loc[i, '坐标X'] = x
            df.loc[i, '坐标Y'] = y
            self.file.read(8)
            point_type = ord(self.file.read(1))
            transparent = ord(self.file.read(1))
            df.loc[i, '透明输出'] = "透明" if transparent else "不透明"
            if point_type == 0:
                df.loc[i, '点类型'] = "字符串"
                df.loc[i, '字符高度'] = round(struct.unpack('1f', self.file.read(4))[0], 8)
                df.loc[i, '字符宽度'] = round(struct.unpack('1f', self.file.read(4))[0], 8)
                df.loc[i, '字符间隔'] = round(struct.unpack('1f', self.file.read(4))[0], 8)
                df.loc[i, '字符串角度'] = round(struct.unpack('1f', self.file.read(4))[0], 8)
                df.loc[i, '中文字体'] = struct.unpack('1h', self.file.read(2))[0]
                df.loc[i, '西文字体'] = struct.unpack('1h', self.file.read(2))[0]
                df.loc[i, '字形'] = ord(self.file.read(1))
                df.loc[i, '排列'] = ord(self.file.read(1))
                char_start, _ = struct.unpack('2i', headers[1][:-2])
                self.file.seek(char_start + char_offset)
                char_text = self.file.read(str_count)
                df.loc[i, '字符串'] = char_text.decode('gb18030')
            elif point_type == 1:
                df.loc[i, '点类型'] = "子图"
                df.loc[i, '子图号'] = struct.unpack('1i', self.file.read(4))[0]
                df.loc[i, '子图高'] = struct.unpack('1f', self.file.read(4))[0]
                df.loc[i, '子图宽'] = struct.unpack('1f', self.file.read(4))[0]
                df.loc[i, '子图角度'] = round(struct.unpack('1f', self.file.read(4))[0], 4)
                df.loc[i, '子图线宽'] = round(struct.unpack('1f', self.file.read(4))[0], 8)
                df.loc[i, '子图辅色'] = struct.unpack('1f', self.file.read(4))[0]
            elif point_type == 2:
                df.loc[i, '点类型'] = "圆"
                df.loc[i, '圆半径'] = round(struct.unpack('1d', self.file.read(8))[0], 8)
                df.loc[i, '圆轮廓颜色'] = struct.unpack('1i', self.file.read(4))[0]
                df.loc[i, '圆笔宽'] = struct.unpack('1f', self.file.read(4))[0]
                fill = ord(self.file.read(1))
                df.loc[i, '圆填充'] = "填充圆" if fill else "空心圆"
            elif point_type == 3:
                df.loc[i, '点类型'] = "弧"
                df.loc[i, '弧半径'] = round(struct.unpack('1d', self.file.read(8))[0], 8)
                df.loc[i, '弧起始角度'] = round(struct.unpack('1f', self.file.read(4))[0], 8)
                df.loc[i, '弧终止角度'] = round(struct.unpack('1f', self.file.read(4))[0], 8)
                df.loc[i, '弧笔宽'] = round(struct.unpack('1f', self.file.read(4))[0], 8)
            self.file.seek(start + 93 * (i + 1) + 73)
            self.file.read(2)
            color = struct.unpack('1i', self.file.read(4))[0]
            df.loc[i, '颜色'] = color
        df.dropna(how='all', axis=1, inplace=True)
        return df

    def _parse_line_info(self, headers):
        """解析线要素详细信息（优化版）。"""
        start, vol = struct.unpack('2i', headers[0][:-2])
        n = int(vol / 57) - 1
        columns = ["ID", "线型", "线颜色", "线宽", "线类型", "X系数", "Y系数", "辅助颜色", "锚点数目", "锚点坐标存储位置"]
        # 一次性读取所有要素的二进制数据
        self.file.seek(start + 57)  # 跳过第一个
        all_bytes = self.file.read(57 * n)
        rows = []
        for i in range(n):
            offset = i * 57
            chunk = all_bytes[offset:offset+57]
            row = {
                "ID": i,
                "锚点数目": struct.unpack('1i', chunk[10:14])[0],
                "锚点坐标存储位置": struct.unpack('1i', chunk[14:18])[0],
                "线型": struct.unpack('1i', chunk[22:26])[0],
                "线颜色": struct.unpack('1i', chunk[26:30])[0],
                "线宽": struct.unpack('1f', chunk[30:34])[0],
                "线类型": chunk[34],
                "X系数": struct.unpack('1f', chunk[35:39])[0],
                "Y系数": struct.unpack('1f', chunk[39:43])[0],
                "辅助颜色": struct.unpack('1i', chunk[43:47])[0],
            }
            rows.append(row)
            self.element_count += 1
        df = pd.DataFrame(rows, columns=columns)
        return df

    def _parse_polygon_info(self, headers):
        """解析面要素详细信息。"""
        columns = ["ID", "填充颜色", "填充符号", "图案高度", "图案宽度", "图案颜色"]
        start, vol = struct.unpack('2i', headers[8][:-2])
        df = pd.DataFrame(columns=columns)
        for i in range(int(vol / 40) - 1):
            self.file.seek(start + 40 * (i + 1))
            df.loc[i, 'ID'] = i
            self.file.read(1)
            self.file.read(4)
            self.file.read(4)
            df.loc[i, '填充颜色'] = struct.unpack('1i', self.file.read(4))[0]
            df.loc[i, '填充符号'] = struct.unpack('1h', self.file.read(2))[0]
            df.loc[i, '图案高度'] = struct.unpack('1f', self.file.read(4))[0]
            df.loc[i, '图案宽度'] = struct.unpack('1f', self.file.read(4))[0]
            self.file.read(2)
            df.loc[i, '图案颜色'] = struct.unpack('1i', self.file.read(4))[0]
            self.element_count += 1
        return df

    def _parse_points(self):
        """解析点要素几何。"""
        self._parse_crs()
        start, vol = struct.unpack('2i', self.headers[0][:-2])
        self.file.seek(start)
        self.file.read(93)
        coords = []
        for _ in range(int(vol / 93) - 1):
            self.file.read(1)
            self.file.read(2)
            self.file.read(4)
            x, y = struct.unpack('2d', self.file.read(16))
            coords.append((x, y))
            self.file.read(70)
        self.coords = np.array(coords)
        scale = self.coordinate_scale if self.coordinate_scale is not None else 1
        self.geom = [shapely.geometry.Point(np.array(xy) * scale) for xy in self.coords]

    def _parse_lines(self):
        """解析线要素几何。"""
        self._parse_crs()
        start, vol = struct.unpack('2i', self.headers[0][:-2])
        self.file.seek(start)
        k = vol // 57
        self.file.read(57)
        points, points_offset = [], []
        for _ in range(k - 1):
            self.file.read(10)
            points.append(struct.unpack('1i', self.file.read(4))[0])
            points_offset.append(struct.unpack('1i', self.file.read(4))[0])
            self.file.read(39)
        start, _ = struct.unpack('2i', self.headers[1][:-2])
        self.coords = []
        for i in range(k - 1):
            self.file.seek(start + points_offset[i])
            self.coords.append(struct.unpack(f'{points[i]*2}d', self.file.read(points[i]*16)))
        scale = self.coordinate_scale if self.coordinate_scale is not None else 1
        self.geom = [shapely.geometry.LineString(np.array(i).reshape(-1, 2) * scale) for i in self.coords]

    def _parse_polygons(self):
        """解析面要素几何。"""
        try:
            self._parse_crs()
            start, vol = struct.unpack('2i', self.headers[0][:-2])
            self.file.seek(start)
            k = vol // 57
            self.file.read(57)
            points, points_offset = [], []
            for _ in range(k - 1):
                self.file.read(10)
                points.append(struct.unpack('1i', self.file.read(4))[0])
                points_offset.append(struct.unpack('1i', self.file.read(4))[0])
                self.file.read(39)
            start, _ = struct.unpack('2i', self.headers[1][:-2])
            self.coords = []
            for i in range(k - 1):
                self.file.seek(start + points_offset[i])
                self.coords.append(struct.unpack(f'{points[i]*2}d', self.file.read(points[i]*16)))
            scale = self.coordinate_scale if self.coordinate_scale is not None else 1
            geom_lines = [shapely.geometry.LineString(np.array(i).reshape(-1, 2) * scale) for i in self.coords]
            start, vol = struct.unpack('2i', self.headers[3][:-2])
            self.file.seek(start)
            self.file.read(24)
            temp = []
            for _ in range(int(vol / 24 - 1)):
                temp.append(struct.unpack('4i', self.file.read(16)))
                self.file.read(8)
            temp = np.array(temp)
            temp = np.hstack((temp, np.arange(temp.shape[0]).reshape((-1, 1))))
            self.geom = []
            for i in set(temp[:, 2:4].flatten()) - {0}:
                mask = (temp[:, 2] == i) | (temp[:, 3] == i)
                x = temp[mask]
                mask_ = x[:, 2] == i
                kk = x[mask_]
                t = kk[:, 0].copy()
                kk[:, 0] = kk[:, 1]
                kk[:, 1] = t
                x[mask_] = kk
                if x.shape[0] == 1:
                    poly = list(geom_lines[x[0][-1]].coords)
                    self.geom.append(shapely.geometry.Polygon(poly))
                else:
                    m = [list(geom_lines[ii[-1]].coords) for ii in x]
                    lines = []
                    while m:
                        ring = m.pop(0)
                        changed = True
                        while changed and m:
                            changed = False
                            for idx, seg in enumerate(m):
                                if np.allclose(ring[-1], seg[0]):
                                    ring.extend(seg[1:])
                                    m.pop(idx)
                                    changed = True
                                    break
                                elif np.allclose(ring[-1], seg[-1]):
                                    ring.extend(seg[-2::-1])
                                    m.pop(idx)
                                    changed = True
                                    break
                                elif np.allclose(ring[0], seg[-1]):
                                    ring = seg[:-1] + ring
                                    m.pop(idx)
                                    changed = True
                                    break
                                elif np.allclose(ring[0], seg[0]):
                                    ring = seg[::-1][:-1] + ring
                                    m.pop(idx)
                                    changed = True
                                    break
                        lines.append(ring)
                    lines = [i for i in lines if len(i) > 2]
                    self.geom.append(shapely.geometry.MultiPolygon(get_multipolygons(lines)))
        except struct.error as e:
            if 'unpack requires a buffer of' in str(e):
                raise Exception("原mapgis文件异常，无法转换，请检查该文件在mapgis中是否能正常保存") from e
            else:
                raise

    def _parse_crs(self):
        """解析坐标系信息。"""
        self.file.seek(109)
        proj_type = ord(self.file.read(1))
        ellipsoid = ord(self.file.read(1))
        self.file.seek(143)
        scale_key = 0
        if self.coordinate_scale is not None:
            self.file.read(8)
            scale_key = 1
        else:
            self.coordinate_scale = struct.unpack('1d', self.file.read(8))[0]
        ellip_dict = {
            1: '+ellps=krass +towgs84=15.8,-154.4,-82.3,0,0,0,0 +units=m +no_d',
            2: '+a=6378140 +b=6356755.288157528',
            7: '+datum=WGS84',
            9: '+ellps=WGS72',
            10: '+ellps=aust_SA +towgs84=-117.808,-51.536,137.784,0.303,0.446,0.234,-0.29',
            11: '+ellps=aust_SA +towgs84=-134,-48,149,0,0,0,0',
            16: '+ellps=krass',
            116: '+ellps=clrk80 +towgs84=-166,-15,204,0,0,0,0',
            'cgcs2000': '+ellps=GRS80',
        }
        if (ellipsoid not in ellip_dict) or (self.coordinate_scale == 0):
            if ellipsoid == 0 and (self.wkid is None or str(self.wkid) == '0'):
                # 椭球体类型为0且wkid为空，crs置空，主程序日志会有详细提示
                self.crs = ''
                return
            if scale_key == 1:
                self.coordinate_scale = self.coordinate_scale / 1000
            else:
                self.coordinate_scale = 1
            self.crs = ''
            
        if proj_type == 5 and self.wkid is None:
            self.file.seek(151)
            cl = struct.unpack('1d', self.file.read(8))[0]
            cl = int(str(cl).split('.')[0][:-4]) + int(str(cl).split('.')[0][-4:-2]) / 60.0 + int(str(cl).split('.')[0][-2:]) / 60.0 / 60
            self.crs = CRS('+proj=tmerc' + f' +lat_0=0 +lon_0={cl} +k=1 +x_0=500000 +y_0=0 ' + ellip_dict[ellipsoid] + ' +units=m +no_defs')
        elif proj_type == 0 and self.wkid is None:
            self.crs = CRS('+proj=longlat ' + ellip_dict[ellipsoid] + ' +no_defs')
        elif proj_type in (2, 3) and self.wkid is None:
            self.coordinate_scale = self.coordinate_scale / 1000
            self.file.seek(151)
            cl = struct.unpack('1d', self.file.read(8))[0]
            cl = int(str(cl).split('.')[0][:-4]) + int(str(cl).split('.')[0][-4:-2]) / 60.0 + int(str(cl).split('.')[0][-2:]) / 60.0 / 60
            self.file.seek(175)
            # 只有在没有指定wkid时才设置crs为None
            if self.wkid is None:
                self.crs = None
        if self.wkid is not None:
            proj = CRS.from_epsg(self.wkid)
            wkt = proj.to_wkt()
            self.crs = CRS(wkt)

    def _build_geodataframe(self):
        """构建 GeoDataFrame。"""
        # 标记是否进行了数据修复
        self._data_repaired = False
        
        try:
            # 标准流程：直接构建GeoDataFrame
            self.geodataframe = gpd.GeoDataFrame(self.data, geometry=self.geom)
            if self.crs:
                self.geodataframe.crs = self.crs
        except ValueError as e:
            # 只有在出现"Length of values"错误时才进行修复
            if "Length of values" in str(e):
                print(f"检测到数据长度不匹配，进行智能修复...")
                print(f"  属性表记录数: {len(self.data)}")
                print(f"  几何对象数: {len(self.geom)}")
                print(f"  差异: {abs(len(self.data) - len(self.geom))}")
                
                # 保守的修复策略：取较小的长度
                min_length = min(len(self.data), len(self.geom))
                print(f"  修复策略: 取前{min_length}个有效数据")
                
                self.data = self.data.iloc[:min_length]
                self.geom = self.geom[:min_length]
                self._data_repaired = True
                
                # 重新构建GeoDataFrame
                self.geodataframe = gpd.GeoDataFrame(self.data, geometry=self.geom)
                if self.crs:
                    self.geodataframe.crs = self.crs
                
                print(f"  修复完成 - 属性表: {len(self.data)}, 几何数据: {len(self.geom)}")
            else:
                # 其他ValueError直接抛出
                raise

    def to_file(self, filepath, **kwargs):
        """保存为文件。"""
        # 通用数值字段异常处理函数，阈值严格按shp字段宽度限制（1e12）
        def fix_large_values(df, column_name, threshold=1e12):
            """修复数值字段中的异常大值，保证shp字段宽度安全"""
            if column_name in df.columns:
                col = df[column_name]
                if col.dtype in ['float64', 'float32', 'int64', 'int32']:
                    large_values = (col.abs() > threshold) | (col.isnull())
                    if large_values.any():
                        print(f"检测到{large_values.sum()}个{column_name}值超出shp字段宽度限制，已自动修正")
                        df.loc[large_values, column_name] = 0.0
        # 处理所有数值字段，阈值为1e12
        numeric_columns = self.geodataframe.select_dtypes(include=['float64', 'float32', 'int64', 'int32']).columns
        for col in numeric_columns:
            fix_large_values(self.geodataframe, col, threshold=1e12)
        # 处理字段名（转换为英文，避免pyogrio警告）
        if filepath.split('.')[-1] == 'shp':
            self.geodataframe = self._sanitize_field_names(self.geodataframe)
        # 保存文件
        self.geodataframe.to_file(filepath, **kwargs)
    
    def _sanitize_field_names(self, df):
        """处理字段名，将中文转换为英文。"""
        # 英文字段名映射
        field_map = {
            'ID': 'ID',
            '面积': 'Area',
            '周长': 'Perimeter',
            'GB': 'GB',
            'Shape_Leng': 'Shape_Leng',
            'Shape_Area': 'Shape_Area',
            'ID-1': 'ID_1',
            '填充颜色': 'FillColor',
            '填充符号': 'FillSymbol',
            '图案高度': 'PatternH',
            '图案宽度': 'PatternW',
            '图案颜色': 'PatternC',
            '坐标X': 'CoordX',
            '坐标Y': 'CoordY',
            '点类型': 'PntType',
            '透明输出': 'TransOut',
            '颜色': 'Color',
            '字符串': 'StrText',
            '字符高度': 'CharH',
            '字符宽度': 'CharW',
            '字符间隔': 'CharSpc',
            '字符串角度': 'StrAng',
            '中文字体': 'FontCN',
            '西文字体': 'FontEN',
            '字形': 'FontSty',
            '排列': 'Arrange',
            '子图号': 'SubNo',
            '子图高': 'SubH',
            '子图宽': 'SubW',
            '子图角度': 'SubAng',
            '子图线宽': 'SubLW',
            '子图辅色': 'SubCol2',
            '圆半径': 'CRadius',
            '圆轮廓颜色': 'CCLR',
            '圆笔宽': 'CPenW',
            '圆填充': 'CFill',
            '弧半径': 'ARadius',
            '弧起始角度': 'AStartAng',
            '弧终止角度': 'AEndAng',
            '弧笔宽': 'APenW',
            '线型': 'LineType',
            '线颜色': 'LineCol',
            '线宽': 'LineWid',
            '线类型': 'LineKind',
            'X系数': 'XFact',
            'Y系数': 'YFact',
            '辅助颜色': 'AuxCol',
        }
        
        new_columns = []
        used = set()
        
        for col in df.columns:
            if col in field_map:
                # 使用映射的英文字段名
                eng_col = field_map[col]
                # 处理重复字段名
                if eng_col in used:
                    idx = 1
                    new_eng_col = f"{eng_col}_{idx}"
                    while new_eng_col in used:
                        idx += 1
                        new_eng_col = f"{eng_col}_{idx}"
                    eng_col = new_eng_col
                new_columns.append(eng_col)
                used.add(eng_col)
            else:
                # 对于未映射的字段，使用拼音转换
                try:
                    import pypinyin
                    pinyin = ''.join([i[0] for i in pypinyin.pinyin(str(col), style=pypinyin.NORMAL)])
                    pinyin = ''.join([c if c.isalnum() or c == '_' else '_' for c in pinyin])
                    if len(pinyin) > 10:
                        pinyin = pinyin[:10]
                    if not pinyin:
                        pinyin = 'field'
                    
                    # 处理重复字段名
                    orig = pinyin
                    idx = 1
                    while pinyin in used:
                        suffix = f"_{idx}"
                        pinyin = (orig[:10-len(suffix)] if len(orig) > 10-len(suffix) else orig) + suffix
                        idx += 1
                    
                    new_columns.append(pinyin)
                    used.add(pinyin)
                except ImportError:
                    # 如果没有pypinyin，使用简单的英文转换
                    eng_name = ''.join([c if c.isalnum() or c == '_' else '_' for c in str(col)])
                    if len(eng_name) > 10:
                        eng_name = eng_name[:10]
                    if not eng_name:
                        eng_name = 'field'
                    
                    # 处理重复字段名
                    orig = eng_name
                    idx = 1
                    while eng_name in used:
                        suffix = f"_{idx}"
                        eng_name = (orig[:10-len(suffix)] if len(orig) > 10-len(suffix) else orig) + suffix
                        idx += 1
                    
                    new_columns.append(eng_name)
                    used.add(eng_name)
        
        df.columns = new_columns
        return df

    def __len__(self):
        return len(self.geom)

    def __str__(self):
        return f"MapGIS文件读取器\n{len(self)} 个要素 (类型: {self.shape_type})"

    def __del__(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__del__()


class InvalidFileError(Exception):
    def __str__(self):
        return "无法识别文件的几何类型"

class InvalidDirectoryError(Exception):
    pass

class TopoError(Exception):
    def __str__(self):
        return "该WP文件存在拓扑错误"

def get_multipolygons(lines):
    """辅助函数：根据线环关系生成多面对象。"""
    n = len(lines)
    relation = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            try:
                inside = shapely.geometry.Polygon(lines[i]).within(shapely.geometry.Polygon(lines[j]))
            except Exception:
                inside = np.array([
                    shapely.geometry.Point(pt).within(shapely.geometry.Polygon(lines[j])) for pt in lines[i]
                ]).any()
            if inside:
                relation[i, j] = 1
    level_0 = {}
    for i in range(n):
        if not (relation[i] == 1).any():
            level_0[i] = [lines[i]]
    for i in range(n):
        if (relation[i] == 1).sum() == 1:
            idx = np.argwhere(relation[i] == 1)[0][0]
            if idx not in level_0:
                level_0[idx] = []
            level_0[idx].append(lines[i])
    if not ((relation == 1).sum(1) == 2).any():
        return [shapely.geometry.Polygon(i[0], i[1:]) for i in level_0.values()]
    else:
        temp = [shapely.geometry.Polygon(i[0], i[1:]) for i in level_0.values()]
        temp.extend(get_multipolygons([lines[i] for i in np.argwhere((relation == 1).sum(1) > 1).flatten()]))
        return temp
