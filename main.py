# coding:utf-8
import logging
import os
import sys
import time
from datetime import datetime
import warnings  # 新增

from PyQt5.QtCore import Qt, QUrl, QThread, pyqtSignal, QCoreApplication
from PyQt5.QtGui import QDesktopServices, QIcon, QIntValidator
from PyQt5.QtWidgets import (
    QFrame, QApplication, QWidget, QHBoxLayout, QVBoxLayout, QFileDialog, QTextEdit
)
from qfluentwidgets import (
    FluentWindow, SubtitleLabel, FluentIcon as FIF, BodyLabel, PushButton, CheckBox, InfoBar, InfoBarPosition,
    HeaderCardWidget,
    setFont, SingleDirectionScrollArea, StateToolTip, GroupHeaderCardWidget,
    ComboBox, EditableComboBox
)

import pymapgis

# ========== 新增：版本号 ==========
VERSION = "v1.0.1"

# ========== 新增：资源路径工具函数 ==========
def get_resource_path(relative_path):
    """获取资源文件的绝对路径，兼容开发和打包环境"""
    if getattr(sys, 'frozen', False):
        # PyInstaller打包环境
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        return os.path.join(base_path, relative_path)
    else:
        # 开发环境
        return os.path.join(os.path.abspath("."), relative_path)


class TitleWidget(QFrame):
    """标题组件"""
    def __init__(self, text: str, parent=None):
        super().__init__(parent=parent)
        self.label = SubtitleLabel(text, self)
        self.hBoxLayout = QHBoxLayout(self)
        setFont(self.label, 24)
        self.label.setAlignment(Qt.AlignCenter)
        self.hBoxLayout.addWidget(self.label, 1, Qt.AlignCenter)
        self.setObjectName(text.replace(' ', '-'))


class MapgisConvertConfigWidget(GroupHeaderCardWidget):
    """Mapgis文件转换配置卡片"""
    class ConvertThread(QThread):
        log_signal = pyqtSignal(str)
        finished_signal = pyqtSignal()
        progress_signal = pyqtSignal(int, int)  # 当前进度, 总数

        def __init__(self, file_paths, output_dir, scale_text, projection_text, use_scale, use_proj, coord_systems, get_key_by_value_func, use_simple_naming, parent=None):
            super().__init__(parent)
            self.file_paths = file_paths
            self.output_dir = output_dir
            self.scale_text = scale_text
            self.projection_text = projection_text
            self.use_scale = use_scale
            self.use_proj = use_proj
            self.coord_systems = coord_systems
            self.get_key_by_value_func = get_key_by_value_func
            self.use_simple_naming = use_simple_naming

        def run(self):
            """执行文件批量转换，支持比例尺和投影坐标系可选"""
            total = len(self.file_paths)
            current = 0
            for mapgis_file in self.file_paths:
                try:
                    start_time = time.time()
                    kwargs = {}
                    if self.use_scale:
                        kwargs['scale_factor'] = int(self.scale_text)
                    if self.use_proj:
                        wkid = self.get_key_by_value_func(self.coord_systems, self.projection_text)
                        kwargs['wkid'] = wkid
                    reader = pymapgis.MapGisReader(mapgis_file, **kwargs)
                    file_base = os.path.splitext(os.path.basename(mapgis_file))[0]
                    file_ext = os.path.splitext(mapgis_file)[1][1:].upper()
                    # 检查crs为空但未抛异常的特殊情况
                    if hasattr(reader, 'crs') and reader.crs == '':
                        self.log_signal.emit(
                            f"ℹ️ 椭球体类型为0，wkid为空，已将坐标系设置为空 | 文件：{os.path.basename(mapgis_file)}"
                        )
                    # 检查是否进行了数据修复
                    elif hasattr(reader, '_data_repaired') and reader._data_repaired:
                        self.log_signal.emit(
                            f"⚠️ 数据已修复 | 文件：{os.path.basename(mapgis_file)} | 已自动处理属性表与几何数据不匹配问题"
                        )
                    else:
                        self.log_signal.emit(
                            f"🕐 {time.strftime('%H:%M:%S')} | ✅ 转换成功 | 文件：{os.path.basename(mapgis_file)}"
                        )
                    
                    # 根据命名方式选择生成文件名
                    if self.use_simple_naming:
                        new_file_path = os.path.join(self.output_dir, f"{file_base}.shp")
                    else:
                        new_file_path = os.path.join(self.output_dir, f"{file_base}_{file_ext}.shp")
                    
                    # 保存文件
                    reader.to_file(new_file_path)
                    
                    end_time = time.time()
                    elapsed_time = end_time - start_time
                    self.log_signal.emit(
                        f"🕐 {time.strftime('%H:%M:%S')} | ✅ 转换完成 | 文件：{os.path.basename(mapgis_file)} | 耗时：{elapsed_time:.2f}秒"
                    )
                    
                except Exception as e:
                    import traceback
                    err_type = type(e).__name__
                    err_detail = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                    
                    # 针对KeyError 0特殊提示
                    if isinstance(e, KeyError) and e.args and e.args[0] == 0:
                        self.log_signal.emit(
                            f"❌ 转换失败 | 文件：{os.path.basename(mapgis_file)} | 错误：椭球体类型为0，未在代码字典中定义，建议用MapGIS重新设置坐标系并保存，或联系开发者。"
                        )
                    else:
                        self.log_signal.emit(
                            f"❌ 转换失败 | 文件：{os.path.basename(mapgis_file)} | 错误类型：{err_type} | 详情：{err_detail}"
                        )
                current += 1
                self.progress_signal.emit(current, total)
            self.log_signal.emit('🎉 全部转换完成！')
            self.finished_signal.emit()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.output_dir = None
        self.selected_files = None
        self.state_tooltip = None
        self.setTitle("转换配置")
        self.setBorderRadius(8)

        # 选择文件按钮
        self.file_button = PushButton(text="选择文件")
        self.file_button.clicked.connect(self.choose_files)
        # 选择输出文件夹按钮
        self.folder_button = PushButton("选择输出文件夹")
        self.folder_button.clicked.connect(self.choose_output_folder)

        # 比例尺输入框
        self.scale_box = EditableComboBox()
        self.scale_box.setFixedWidth(100)
        self.scale_box.setEnabled(False)
        self.scale_box.setValidator(QIntValidator())
        self.scale_box.addItems(['200000', '100000', '50000', '10000', '5000', '2000'])

        # 指定比例尺复选框
        self.scale_checkbox = CheckBox('指定比例尺', self)
        self.scale_checkbox.clicked.connect(self.toggle_scale_box)

        # 比例尺控件布局
        self.scale_widget = QWidget()
        self.scale_layout = QHBoxLayout(self.scale_widget)
        self.scale_layout.setSpacing(50)
        self.scale_layout.addWidget(self.scale_checkbox)
        self.scale_layout.addWidget(self.scale_box)

        self.file_button.setFixedWidth(120)

        # 指定投影坐标系复选框
        self.proj_checkbox = CheckBox('指定坐标系', self)
        self.proj_checkbox.clicked.connect(self.toggle_projection_box)
        self.projection_combo = ComboBox()

        # 常用坐标系字典
        self.common_coord_systems = {'4214': 'GCS_Beijing_1954', '4326': 'GCS_WGS_1984',
                                          '4490': 'GCS_China_Geodetic_Coordinate_System_2000',
                                          '4555': 'GCS_New_Beijing', '4610': 'GCS_Xian_1980',
                                          '2327': 'Xian_1980_GK_Zone_13',
                                          '2328': 'Xian_1980_GK_Zone_14', '2329': 'Xian_1980_GK_Zone_15',
                                          '2330': 'Xian_1980_GK_Zone_16',
                                          '2331': 'Xian_1980_GK_Zone_17', '2332': 'Xian_1980_GK_Zone_18',
                                          '2333': 'Xian_1980_GK_Zone_19',
                                          '2334': 'Xian_1980_GK_Zone_20', '2335': 'Xian_1980_GK_Zone_21',
                                          '2336': 'Xian_1980_GK_Zone_22',
                                          '2337': 'Xian_1980_GK_Zone_23', '2338': 'Xian_1980_GK_CM_75E',
                                          '2339': 'Xian_1980_GK_CM_81E',
                                          '2340': 'Xian_1980_GK_CM_87E', '2341': 'Xian_1980_GK_CM_93E',
                                          '2342': 'Xian_1980_GK_CM_99E',
                                          '2343': 'Xian_1980_GK_CM_105E', '2344': 'Xian_1980_GK_CM_111E',
                                          '2345': 'Xian_1980_GK_CM_117E',
                                          '2346': 'Xian_1980_GK_CM_123E', '2347': 'Xian_1980_GK_CM_129E',
                                          '2348': 'Xian_1980_GK_CM_135E',
                                          '2349': 'Xian_1980_3_Degree_GK_Zone_25',
                                          '2350': 'Xian_1980_3_Degree_GK_Zone_26',
                                          '2351': 'Xian_1980_3_Degree_GK_Zone_27',
                                          '2352': 'Xian_1980_3_Degree_GK_Zone_28',
                                          '2353': 'Xian_1980_3_Degree_GK_Zone_29',
                                          '2354': 'Xian_1980_3_Degree_GK_Zone_30',
                                          '2355': 'Xian_1980_3_Degree_GK_Zone_31',
                                          '2356': 'Xian_1980_3_Degree_GK_Zone_32',
                                          '2357': 'Xian_1980_3_Degree_GK_Zone_33',
                                          '2358': 'Xian_1980_3_Degree_GK_Zone_34',
                                          '2359': 'Xian_1980_3_Degree_GK_Zone_35',
                                          '2360': 'Xian_1980_3_Degree_GK_Zone_36',
                                          '2361': 'Xian_1980_3_Degree_GK_Zone_37',
                                          '2362': 'Xian_1980_3_Degree_GK_Zone_38',
                                          '2363': 'Xian_1980_3_Degree_GK_Zone_39',
                                          '2364': 'Xian_1980_3_Degree_GK_Zone_40',
                                          '2365': 'Xian_1980_3_Degree_GK_Zone_41',
                                          '2366': 'Xian_1980_3_Degree_GK_Zone_42',
                                          '2367': 'Xian_1980_3_Degree_GK_Zone_43',
                                          '2368': 'Xian_1980_3_Degree_GK_Zone_44',
                                          '2369': 'Xian_1980_3_Degree_GK_Zone_45',
                                          '2370': 'Xian_1980_3_Degree_GK_CM_75E',
                                          '2371': 'Xian_1980_3_Degree_GK_CM_78E',
                                          '2372': 'Xian_1980_3_Degree_GK_CM_81E',
                                          '2373': 'Xian_1980_3_Degree_GK_CM_84E',
                                          '2374': 'Xian_1980_3_Degree_GK_CM_87E',
                                          '2375': 'Xian_1980_3_Degree_GK_CM_90E',
                                          '2376': 'Xian_1980_3_Degree_GK_CM_93E',
                                          '2377': ' Xian_1980_3_Degree_GK_CM_96E',
                                          '2378': 'Xian_1980_3_Degree_GK_CM_99E',
                                          '2379': 'Xian_1980_3_Degree_GK_CM_102E',
                                          '2380': 'Xian_1980_3_Degree_GK_CM_105E',
                                          '2381': 'Xian_1980_3_Degree_GK_CM_108E',
                                          '2382': 'Xian_1980_3_Degree_GK_CM_111E',
                                          '2383': 'Xian_1980_3_Degree_GK_CM_114E',
                                          '2384': 'Xian_1980_3_Degree_GK_CM_117E',
                                          '2385': 'Xian_1980_3_Degree_GK_CM_120E',
                                          '2386': 'Xian_1980_3_Degree_GK_CM_123E',
                                          '2387': 'Xian_1980_3_Degree_GK_CM_126E',
                                          '2388': 'Xian_1980_3_Degree_GK_CM_129E',
                                          '2389': 'Xian_1980_3_Degree_GK_CM_132E',
                                          '2390': 'Xian_1980_3_Degree_GK_CM_135E',
                                          '2401': 'Beijing_1954_3_Degree_GK_Zone_25',
                                          '2402': 'Beijing_1954_3_Degree_GK_Zone_26',
                                          '2403': 'Beijing_1954_3_Degree_GK_Zone_27',
                                          '2404': 'Beijing_1954_3_Degree_GK_Zone_28',
                                          '2405': 'Beijing_1954_3_Degree_GK_Zone_29',
                                          '2406': 'Beijing_1954_3_Degree_GK_Zone_30',
                                          '2407': 'Beijing_1954_3_Degree_GK_Zone_31',
                                          '2408': 'Beijing_1954_3_Degree_GK_Zone_32',
                                          '2409': 'Beijing_1954_3_Degree_GK_Zone_33',
                                          '2410': 'Beijing_1954_3_Degree_GK_Zone_34',
                                          '2411': 'Beijing_1954_3_Degree_GK_Zone_35',
                                          '2412': 'Beijing_1954_3_Degree_GK_Zone_36',
                                          '2413': 'Beijing_1954_3_Degree_GK_Zone_37',
                                          '2414': 'Beijing_1954_3_Degree_GK_Zone_38',
                                          '2415': 'Beijing_1954_3_Degree_GK_Zone_39',
                                          '2416': 'Beijing_1954_3_Degree_GK_Zone_40',
                                          '2417': 'Beijing_1954_3_Degree_GK_Zone_41',
                                          '2418': 'Beijing_1954_3_Degree_GK_Zone_42',
                                          '2419': 'Beijing_1954_3_Degree_GK_Zone_43',
                                          '2420': 'Beijing_1954_3_Degree_GK_Zone_44',
                                          '2421': 'Beijing_1954_3_Degree_GK_Zone_45',
                                          '2422': 'Beijing_1954_3_Degree_GK_CM_75E',
                                          '2423': 'Beijing_1954_3_Degree_GK_CM_78E',
                                          '2424': 'Beijing_1954_3_Degree_GK_CM_81E',
                                          '2425': 'Beijing_1954_3_Degree_GK_CM_84E',
                                          '2426': 'Beijing_1954_3_Degree_GK_CM_87E',
                                          '2427': 'Beijing_1954_3_Degree_GK_CM_90E',
                                          '2428': 'Beijing_1954_3_Degree_GK_CM_93E',
                                          '2429': 'Beijing_1954_3_Degree_GK_CM_96E',
                                          '2430': 'Beijing_1954_3_Degree_GK_CM_99E',
                                          '2431': 'Beijing_1954_3_Degree_GK_CM_102E',
                                          '2432': 'Beijing_1954_3_Degree_GK_CM_105E',
                                          '2433': 'Beijing_1954_3_Degree_GK_CM_108E',
                                          '2434': 'Beijing_1954_3_Degree_GK_CM_111E',
                                          '2435': 'Beijing_1954_3_Degree_GK_CM_114E',
                                          '2436': 'Beijing_1954_3_Degree_GK_CM_117E',
                                          '2437': 'Beijing_1954_3_Degree_GK_CM_120E',
                                          '2438': 'Beijing_1954_3_Degree_GK_CM_123E',
                                          '2439': 'Beijing_1954_3_Degree_GK_CM_126E',
                                          '2440': 'Beijing_1954_3_Degree_GK_CM_129E',
                                          '2441': 'Beijing_1954_3_Degree_GK_CM_132E',
                                          '2442': 'Beijing_1954_3_Degree_GK_CM_135E', '3395': 'WGS_1984_World_Mercator',
                                          '4491': 'CGCS2000_GK_Zone_13',
                                          '4492': 'CGCS2000_GK_Zone_14', '4493': 'CGCS2000_GK_Zone_15',
                                          '4494': 'CGCS2000_GK_Zone_16',
                                          '4495': 'CGCS2000_GK_Zone_17', '4496': 'CGCS2000_GK_Zone_18',
                                          '4497': 'CGCS2000_GK_Zone_19',
                                          '4498': 'CGCS2000_GK_Zone_20', '4499': 'CGCS2000_GK_Zone_21',
                                          '4500': 'CGCS2000_GK_Zone_22',
                                          '4501': 'CGCS2000_GK_Zone_23', '4502': 'CGCS2000_GK_CM_75E',
                                          '4503': 'CGCS2000_GK_CM_81E',
                                          '4504': 'CGCS2000_GK_CM_87E', '4505': 'CGCS2000_GK_CM_93E',
                                          '4506': 'CGCS2000_GK_CM_99E',
                                          '4507': 'CGCS2000_GK_CM_105E', '4508': 'CGCS2000_GK_CM_111E',
                                          '4509': 'CGCS2000_GK_CM_117E',
                                          '4510': 'CGCS2000_GK_CM_123E', '4511': 'CGCS2000_GK_CM_129E',
                                          '4512': 'CGCS2000_GK_CM_135E',
                                          '4513': 'CGCS2000_3_Degree_GK_Zone_25',
                                          '4514': 'CGCS2000_3_Degree_GK_Zone_26',
                                          '4515': 'CGCS2000_3_Degree_GK_Zone_27',
                                          '4516': 'CGCS2000_3_Degree_GK_Zone_28',
                                          '4517': 'CGCS2000_3_Degree_GK_Zone_29',
                                          '4518': 'CGCS2000_3_Degree_GK_Zone_30',
                                          '4519': 'CGCS2000_3_Degree_GK_Zone_31',
                                          '4520': 'CGCS2000_3_Degree_GK_Zone_32',
                                          '4521': 'CGCS2000_3_Degree_GK_Zone_33',
                                          '4522': 'CGCS2000_3_Degree_GK_Zone_34',
                                          '4523': 'CGCS2000_3_Degree_GK_Zone_35',
                                          '4524': 'CGCS2000_3_Degree_GK_Zone_36',
                                          '4525': 'CGCS2000_3_Degree_GK_Zone_37',
                                          '4526': 'CGCS2000_3_Degree_GK_Zone_38',
                                          '4527': 'CGCS2000_3_Degree_GK_Zone_39',
                                          '4528': 'CGCS2000_3_Degree_GK_Zone_40',
                                          '4529': 'CGCS2000_3_Degree_GK_Zone_41',
                                          '4530': 'CGCS2000_3_Degree_GK_Zone_42',
                                          '4531': 'CGCS2000_3_Degree_GK_Zone_43',
                                          '4532': 'CGCS2000_3_Degree_GK_Zone_44',
                                          '4533': 'CGCS2000_3_Degree_GK_Zone_45', '4534': 'CGCS2000_3_Degree_GK_CM_75E',
                                          '4535': 'CGCS2000_3_Degree_GK_CM_78E', '4536': 'CGCS2000_3_Degree_GK_CM_81E',
                                          '4537': 'CGCS2000_3_Degree_GK_CM_84E', '4538': 'CGCS2000_3_Degree_GK_CM_87E',
                                          '4539': 'CGCS2000_3_Degree_GK_CM_90E', '4540': 'CGCS2000_3_Degree_GK_CM_93E',
                                          '4541': 'CGCS2000_3_Degree_GK_CM_96E', '4542': 'CGCS2000_3_Degree_GK_CM_99E',
                                          '4543': 'CGCS2000_3_Degree_GK_CM_102E',
                                          '4544': 'CGCS2000_3_Degree_GK_CM_105E',
                                          '4545': 'CGCS2000_3_Degree_GK_CM_108E',
                                          '4546': 'CGCS2000_3_Degree_GK_CM_111E',
                                          '4547': 'CGCS2000_3_Degree_GK_CM_114E',
                                          '4548': 'CGCS2000_3_Degree_GK_CM_117E',
                                          '4549': 'CGCS2000_3_Degree_GK_CM_120E',
                                          '4550': 'CGCS2000_3_Degree_GK_CM_123E',
                                          '4551': 'CGCS2000_3_Degree_GK_CM_126E',
                                          '4552': 'CGCS2000_3_Degree_GK_CM_129E',
                                          '4553': 'CGCS2000_3_Degree_GK_CM_132E',
                                          '4554': 'CGCS2000_3_Degree_GK_CM_135E',
                                          '4568': 'New_Beijing_Gauss_Kruger_Zone_13',
                                          '4569': 'New_Beijing_Gauss_Kruger_Zone_14',
                                          '4570': 'New_Beijing_Gauss_Kruger_Zone_15',
                                          '4571': 'New_Beijing_Gauss_Kruger_Zone_16',
                                          '4572': 'New_Beijing_Gauss_Kruger_Zone_17',
                                          '4573': 'New_Beijing_Gauss_Kruger_Zone_18',
                                          '4574': 'New_Beijing_Gauss_Kruger_Zone_19',
                                          '4575': 'New_Beijing_Gauss_Kruger_Zone_20',
                                          '4576': 'New_Beijing_Gauss_Kruger_Zone_21',
                                          '4577': 'New_Beijing_Gauss_Kruger_Zone_22',
                                          '4578': 'New_Beijing_Gauss_Kruger_Zone_23',
                                          '4579': 'New_Beijing_Gauss_Kruger_CM_75E',
                                          '4580': 'New_Beijing_Gauss_Kruger_CM_81E',
                                          '4581': 'New_Beijing_Gauss_Kruger_CM_87E',
                                          '4582': 'New_Beijing_Gauss_Kruger_CM_93E',
                                          '4583': 'New_Beijing_Gauss_Kruger_CM_99E',
                                          '4584': 'New_Beijing_Gauss_Kruger_CM_105E',
                                          '4585': 'New_Beijing_Gauss_Kruger_CM_111E',
                                          '4586': 'New_Beijing_Gauss_Kruger_CM_117E',
                                          '4587': 'New_Beijing_Gauss_Kruger_CM_123E',
                                          '4588': 'New_Beijing_Gauss_Kruger_CM_129E',
                                          '4589': 'New_Beijing_Gauss_Kruger_CM_135E',
                                          '4652': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_25',
                                          '4653': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_26',
                                          '4654': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_27',
                                          '4655': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_28',
                                          '4656': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_29',
                                          '4766': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_30',
                                          '4767': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_31',
                                          '4768': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_32',
                                          '4769': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_33',
                                          '4770': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_34',
                                          '4771': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_35',
                                          '4772': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_36',
                                          '4773': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_37',
                                          '4774': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_38',
                                          '4775': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_39',
                                          '4776': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_40',
                                          '4777': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_41',
                                          '4778': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_42',
                                          '4779': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_43',
                                          '4780': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_44',
                                          '4781': 'New_Beijing_3_Degree_Gauss_Kruger_Zone_45',
                                          '4782': 'New_Beijing_3_Degree_Gauss_Kruger_CM_75E',
                                          '4783': 'New_Beijing_3_Degree_Gauss_Kruger_CM_78E',
                                          '4784': 'New_Beijing_3_Degree_Gauss_Kruger_CM_81E',
                                          '4785': 'New_Beijing_3_Degree_Gauss_Kruger_CM_84E',
                                          '4786': 'New_Beijing_3_Degree_Gauss_Kruger_CM_87E',
                                          '4787': 'New_Beijing_3_Degree_Gauss_Kruger_CM_90E',
                                          '4788': 'New_Beijing_3_Degree_Gauss_Kruger_CM_93E',
                                          '4789': 'New_Beijing_3_Degree_Gauss_Kruger_CM_96E',
                                          '4790': 'New_Beijing_3_Degree_Gauss_Kruger_CM_99E',
                                          '4791': 'New_Beijing_3_Degree_Gauss_Kruger_CM_102E',
                                          '4792': 'New_Beijing_3_Degree_Gauss_Kruger_CM_105E',
                                          '4793': 'New_Beijing_3_Degree_Gauss_Kruger_CM_108E',
                                          '4794': 'New_Beijing_3_Degree_Gauss_Kruger_CM_111E',
                                          '4795': 'New_Beijing_3_Degree_Gauss_Kruger_CM_114E',
                                          '4796': 'New_Beijing_3_Degree_Gauss_Kruger_CM_117E',
                                          '4797': 'New_Beijing_3_Degree_Gauss_Kruger_CM_120E',
                                          '4798': 'New_Beijing_3_Degree_Gauss_Kruger_CM_123E',
                                          '4799': 'New_Beijing_3_Degree_Gauss_Kruger_CM_126E',
                                          '4800': 'New_Beijing_3_Degree_Gauss_Kruger_CM_129E',
                                          '4822': 'New_Beijing_3_Degree_Gauss_Kruger_CM_135E'}

        # 获取common_coordinate_systems的各个值作为坐标系名称列表
        list_coordinate_system_names = list(self.common_coord_systems.values())
        self.projection_combo.setFixedWidth(320)
        self.projection_combo.addItems(list_coordinate_system_names)
        self.projection_combo.setEnabled(False)

        # 投影控件布局
        self.projection_widget = QWidget()
        self.projection_layout = QHBoxLayout(self.projection_widget)
        self.projection_layout.setSpacing(50)
        self.projection_layout.addWidget(self.proj_checkbox)
        self.projection_layout.addWidget(self.projection_combo)

        # 文件命名方式单选框
        self.naming_checkbox = CheckBox('直接替换后缀', self)
        self.naming_checkbox.setToolTip('勾选后文件名直接替换后缀为shp，不勾选则保持原命名方式')
        
        # 转换按钮
        self.convert_button = PushButton(text="开始转换")
        self.convert_button.clicked.connect(self.start_conversion)
        
        # 保存日志勾选框（新增）
        self.save_log_checkbox = CheckBox('保存日志', self)
        self.save_log_checkbox.setChecked(True)
        self.save_log_checkbox.setToolTip('勾选后将转换日志保存到输出文件夹')
        
        # 转换控件布局
        self.convert_widget = QWidget()
        self.convert_layout = QHBoxLayout(self.convert_widget)
        self.convert_layout.setContentsMargins(20, 0, 0, 0)  # 左侧留出20px间距
        self.convert_layout.setSpacing(20)  # 增加组件间距
        self.convert_layout.addWidget(self.save_log_checkbox)  # 新增：保存日志勾选框
        self.convert_layout.addWidget(self.naming_checkbox)
        self.convert_layout.addWidget(self.convert_button)
        self.convert_layout.addStretch()

        # 卡片分组（资源路径替换）
        self.file_group = self.addGroup(get_resource_path("resource/文件.svg"), "选择Mapgis文件", "选择需要转换的Mapgis文件", self.file_button)
        self.folder_group = self.addGroup(get_resource_path("resource/文件夹.svg"), "选择输出文件夹", "选择转换后的文件输出路径", self.folder_button)
        self.addGroup(get_resource_path("resource/比例尺.png"), "指定比例尺 ", "设置指定转换的比例尺", self.scale_widget)
        self.addGroup(get_resource_path("resource/坐标系.png"), "指定转换坐标系", "指定转换后的坐标系", self.projection_widget)
        self.convert_group = self.addGroup(get_resource_path("resource/开始.png"), "执行mapgis文件转换", "转换进度", self.convert_widget)

    def choose_files(self):
        """选择Mapgis文件"""
        options = QFileDialog.Options()
        self.selected_files, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", "Mapgis文件 (*.wt *.wp *.wl);", options=options)
        if self.selected_files:
            self.file_group.setContent(f"已选择{len(self.selected_files)}个mapgis文件")

    def choose_output_folder(self):
        """选择输出文件夹"""
        options = QFileDialog.Options()
        self.output_dir = QFileDialog.getExistingDirectory(self, "选择文件夹", "", options=options)
        if self.output_dir:
            self.folder_group.setContent("已选择输出文件夹")

    def toggle_scale_box(self):
        """切换比例尺输入框可用状态"""
        self.scale_box.setEnabled(self.scale_checkbox.isChecked())

    def toggle_projection_box(self):
        """切换投影下拉框可用状态"""
        self.projection_combo.setEnabled(self.proj_checkbox.isChecked())

    @staticmethod
    def get_key_by_value(d, value):
        """通过value查找字典key"""
        return str([k for k, v in d.items() if v == value][0])

    def start_conversion(self):
        """开始批量转换文件"""
        if not self.selected_files:
            InfoBar.error(
                title='错误',
                content="未选择需要转换的文件",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=1000,
                parent=self
            )
            return
        if not self.output_dir:
            InfoBar.error(
                title='错误',
                content="未选择输出文件夹",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=1000,
                parent=self
            )
            return
        
        # 输出转换配置信息到日志窗口
        self.log_conversion_config()
        
        # 获取当前时间作为日志文件名
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_filename = f"转换日志_{current_time}.txt"
        
        self.state_tooltip = StateToolTip('正在转换文件', f'已转换 0/{len(self.selected_files)} 个文件', self)
        self.state_tooltip.move(600, 0)
        self.state_tooltip.setEnabled(False)
        self.state_tooltip.show()
        self.convert_button.setEnabled(False)
        # 启动转换线程
        self.convert_thread = self.ConvertThread(
            self.selected_files,
            self.output_dir,
            self.scale_box.text(),
            self.projection_combo.text(),
            self.scale_checkbox.isChecked(),
            self.proj_checkbox.isChecked(),
            self.common_coord_systems,
            self.get_key_by_value,
            self.naming_checkbox.isChecked()
        )
        self.convert_thread.log_signal.connect(self.handle_log)
        self.convert_thread.finished_signal.connect(self.handle_convert_finished)
        self.convert_thread.progress_signal.connect(self.handle_progress)
        self.convert_thread.start()

    def log_conversion_config(self):
        """输出转换配置信息到日志窗口"""
        config_lines = [
            "=" * 60,
            "📋 转换配置信息",
            "=" * 60,
            f"📁 输出目录: {self.output_dir}",
            f"📄 待转换文件数: {len(self.selected_files)}",
            "📄 待转换文件列表:"
        ]
        for i, file_path in enumerate(self.selected_files, 1):
            config_lines.append(f"   {i}. {os.path.basename(file_path)}")
        config_lines.extend([
            f"🔧 比例尺设置: {'启用' if self.scale_checkbox.isChecked() else '禁用'}",
            f"🌍 投影坐标系设置: {'启用' if self.proj_checkbox.isChecked() else '禁用'}",
            f"📝 文件命名方式: {'直接替换后缀' if self.naming_checkbox.isChecked() else '保持原命名方式'}",
            "=" * 60,
            "🚀 开始转换...",
            "=" * 60
        ])
        if self.scale_checkbox.isChecked():
            config_lines.insert(-3, f"   比例尺值: {self.scale_box.text()}")
        if self.proj_checkbox.isChecked():
            config_lines.insert(-3, f"   坐标系: {self.projection_combo.text()}")
        # 统一通过日志信号输出，避免子线程直接操作UI
        for line in config_lines:
            self.handle_log(line)

    def handle_progress(self, current, total):
        """更新进度显示"""
        progress_text = f"已转换 {current}/{total} 个文件"
        self.convert_group.setContent(progress_text)
        # 同步更新StateToolTip的显示文本
        if self.state_tooltip:
            self.state_tooltip.setContent(progress_text)

    def handle_log(self, msg):
        """日志输出（只允许主线程操作UI）"""
        # 确保消息格式正确，添加换行符
        if not msg.endswith('\n'):
            msg = msg + '\n'
        # 只允许主线程操作UI
        if QThread.currentThread() == QCoreApplication.instance().thread():
            # 主线程，安全操作UI
            if getattr(sys, 'frozen', False):
                main_window = self.window()
                if hasattr(main_window, 'logInterface'):
                    main_window.logInterface.append_log(msg)
                else:
                    print(msg, end='')
            else:
                print(msg, end='')
        else:
            # 子线程，转发到主线程
            self.log_signal.emit(msg)

    def handle_convert_finished(self):
        """转换完成处理"""
        self.convert_group.setContent("")
        if self.state_tooltip:
            self.state_tooltip.hide()
        self.convert_button.setEnabled(True)
        
        # 仅在勾选保存日志时才保存日志文件（新增）
        if self.save_log_checkbox.isChecked():
            self.save_log_to_file()
        
        InfoBar.success(
            title='成功',
            content="文件转换已完成",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=2000,
            parent=self
        )
    
    def save_log_to_file(self):
        """将日志内容保存到文件"""
        try:
            # 获取主窗口的日志界面
            from PyQt5.QtCore import QThread, QCoreApplication
            if QThread.currentThread() == QCoreApplication.instance().thread():
                main_window = self.window()
                if hasattr(main_window, 'logInterface'):
                    log_content = main_window.logInterface.textEdit.toPlainText()
                    log_file_path = os.path.join(self.output_dir, self.log_filename)
                    with open(log_file_path, 'w', encoding='utf-8') as f:
                        f.write(f"MapGIS文件转换日志\n")
                        f.write(f"转换时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"输出目录: {self.output_dir}\n")
                        f.write(f"转换文件数: {len(self.selected_files)}\n")
                        f.write("-" * 50 + "\n")
                        f.write(log_content)
                    # 使用handle_log方法确保日志格式一致
                    self.handle_log(f"📄 日志文件已保存: {self.log_filename}")
            else:
                # 子线程，转发到主线程
                self.log_signal.emit(f"📄 日志文件已保存: {self.log_filename}")
        except Exception as e:
            self.handle_log(f"❌ 保存日志文件失败: {e}")


class FAQCardWidget(HeaderCardWidget):
    """疑难解答卡片"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("faqCard")
        self.faqLabel = BodyLabel()
        self.faqLabel.setText('''<p style='line-height:25px;'>
        <b>Q1: 这是一个临时问题？</b><br/>
        A1: 这是临时的疑难解答内容。<br/><br/>
        <b>Q2: 还有其他问题吗？</b><br/>
        A2: 这里会展示常见问题的解答。
        </p>''')
        self.faqLabel.setWordWrap(True)
        self.faqLabel.setOpenExternalLinks(True)
        self.faqLabel.adjustSize()
        self.viewLayout.addWidget(self.faqLabel)
        self.setTitle('疑难解答')
        self.setBorderRadius(8)


class AboutWidget(SingleDirectionScrollArea):
    """软件介绍页面，展示项目信息和作者信息"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aboutInterface")
        
        # 创建内容容器
        self.contentWidget = QWidget()
        self.contentLayout = QVBoxLayout(self.contentWidget)
        self.contentLayout.setSpacing(20)
        self.contentLayout.setContentsMargins(20, 20, 20, 20)
        
        # 项目信息卡片
        self.projectCard = HeaderCardWidget(self.contentWidget)
        self.projectCard.setTitle("项目信息")
        self.projectCard.setBorderRadius(8)
        self.setup_project_info()
        
        # 功能特性卡片
        self.featuresCard = HeaderCardWidget(self.contentWidget)
        self.featuresCard.setTitle("功能特性")
        self.featuresCard.setBorderRadius(8)
        self.setup_features_info()
        
        # 作者信息卡片
        self.authorCard = HeaderCardWidget(self.contentWidget)
        self.authorCard.setTitle("作者信息")
        self.authorCard.setBorderRadius(8)
        self.setup_author_info()
        
        # 致谢卡片
        self.thanksCard = HeaderCardWidget(self.contentWidget)
        self.thanksCard.setTitle("致谢")
        self.thanksCard.setBorderRadius(8)
        self.setup_thanks_info()
        
        # 添加卡片到布局
        self.contentLayout.addWidget(self.projectCard)
        self.contentLayout.addWidget(self.featuresCard)
        self.contentLayout.addWidget(self.authorCard)
        self.contentLayout.addWidget(self.thanksCard)
        self.contentLayout.addStretch()
        
        # 设置滚动区域
        self.setWidget(self.contentWidget)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
    
    def setup_project_info(self):
        """设置项目信息"""
        project_layout = QVBoxLayout()
        project_layout.setSpacing(16)
        
        # 项目标题
        title_label = SubtitleLabel("ConvertMapGIS", self)
        setFont(title_label, 24)
        title_label.setAlignment(Qt.AlignCenter)
        project_layout.addWidget(title_label)
        
        # 项目描述
        desc_label = BodyLabel()
        desc_html = '''
        <div style="text-align: center; margin: 16px 0;">
            <p style="font-size: 16px; color: #666; line-height: 1.6;">
                一个基于Python的MapGIS文件转换工具，支持将MapGIS格式文件转换为Shapefile格式。
            </p>
            <p style="font-size: 14px; color: #888; line-height: 1.5;">
                基于pymapgis项目重构优化，大幅提升转换速度，新增比例尺和坐标系指定功能。
            </p>
        </div>
        '''
        desc_label.setText(desc_html)
        desc_label.setWordWrap(True)
        desc_label.setOpenExternalLinks(True)
        project_layout.addWidget(desc_label)
        
        # 项目链接
        link_layout = QHBoxLayout()
        link_layout.setSpacing(12)
        
        github_btn = PushButton("GitHub 项目地址", self)
        github_btn.setIcon(FIF.GITHUB)
        github_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/BenChao1998/ConvertMapGIS")))
        
        releases_btn = PushButton("下载最新版本", self)
        releases_btn.setIcon(FIF.DOWNLOAD)
        releases_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/BenChao1998/ConvertMapGIS/releases")))
        
        link_layout.addWidget(github_btn)
        link_layout.addWidget(releases_btn)
        link_layout.addStretch()
        
        project_layout.addLayout(link_layout)
        self.projectCard.viewLayout.addLayout(project_layout)
    
    def setup_features_info(self):
        """设置功能特性信息"""
        features_layout = QVBoxLayout()
        features_layout.setSpacing(12)
        
        features_html = '''
        <div style="line-height: 1.8;">
            <div style="display: flex; align-items: center; margin: 8px 0;">
                <span style="color: #0078d4; font-size: 18px; margin-right: 12px;">🗺️</span>
                <span>支持MapGIS点、线、面要素的转换</span>
            </div>
            <div style="display: flex; align-items: center; margin: 8px 0;">
                <span style="color: #0078d4; font-size: 18px; margin-right: 12px;">🔄</span>
                <span>批量文件转换功能</span>
            </div>
            <div style="display: flex; align-items: center; margin: 8px 0;">
                <span style="color: #0078d4; font-size: 18px; margin-right: 12px;">📏</span>
                <span>支持自定义比例尺和坐标系</span>
            </div>
            <div style="display: flex; align-items: center; margin: 8px 0;">
                <span style="color: #0078d4; font-size: 18px; margin-right: 12px;">⚡</span>
                <span>优化转换速度，大幅提升性能</span>
            </div>
            <div style="display: flex; align-items: center; margin: 8px 0;">
                <span style="color: #0078d4; font-size: 18px; margin-right: 12px;">🎨</span>
                <span>现代化的PyQt5图形界面</span>
            </div>
            <div style="display: flex; align-items: center; margin: 8px 0;">
                <span style="color: #0078d4; font-size: 18px; margin-right: 12px;">📝</span>
                <span>详细的转换日志记录</span>
            </div>
        </div>
        '''
        
        features_label = BodyLabel()
        features_label.setText(features_html)
        features_label.setWordWrap(True)
        features_layout.addWidget(features_label)
        
        self.featuresCard.viewLayout.addLayout(features_layout)
    
    def setup_author_info(self):
        """设置作者信息"""
        author_layout = QVBoxLayout()
        author_layout.setSpacing(16)
        
        # 作者信息
        author_html = '''
        <div style="text-align: center; margin: 16px 0;">
            <div style="margin-bottom: 16px;">
                <p style="font-size: 18px; font-weight: bold; color: #333; margin: 8px 0;">
                    BenChao
                </p>
            </div>
 
        </div>
        '''
        
        author_label = BodyLabel()
        author_label.setText(author_html)
        author_label.setWordWrap(True)
        author_layout.addWidget(author_label)
        
        # 作者链接
        author_links_layout = QHBoxLayout()
        author_links_layout.setSpacing(12)
        
        github_profile_btn = PushButton("GitHub 主页", self)
        github_profile_btn.setIcon(FIF.GITHUB)
        github_profile_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/BenChao1998")))
        
        author_links_layout.addWidget(github_profile_btn)
        author_links_layout.addStretch()
        
        author_layout.addLayout(author_links_layout)
        self.authorCard.viewLayout.addLayout(author_layout)
    
    def setup_thanks_info(self):
        """设置致谢信息"""
        thanks_layout = QVBoxLayout()
        thanks_layout.setSpacing(16)
        
        thanks_html = '''
        <div style="line-height: 1.8;">
            <div style="margin-bottom: 16px;">
                <p style="font-size: 16px; font-weight: bold; color: #333; margin: 8px 0;">
                    特别感谢以下开源项目：
                </p>
            </div>
            <div style="background: #f8f9fa; padding: 16px; border-radius: 8px; margin: 12px 0;">
                <div style="display: flex; align-items: center; margin: 8px 0;">
                    <span style="color: #0078d4; font-size: 16px; margin-right: 12px;">📚</span>
                    <span><strong>pymapgis</strong> - 基于此项目进行开发</span>
                </div>
                <div style="margin-left: 28px; margin-top: 4px;">
                    <p style="font-size: 13px; color: #666; margin: 4px 0;">
                        原作者：<a href="https://github.com/leecugb" style="color: #0078d4;">leecugb</a>
                    </p>
                </div>
            </div>
            <div style="background: #f8f9fa; padding: 16px; border-radius: 8px; margin: 12px 0;">
                <div style="display: flex; align-items: center; margin: 8px 0;">
                    <span style="color: #0078d4; font-size: 16px; margin-right: 12px;">🎨</span>
                    <span><strong>PyQt-Fluent-Widgets</strong> - 现代化UI组件库</span>
                </div>
                <div style="margin-left: 28px; margin-top: 4px;">
                    <p style="font-size: 13px; color: #666; margin: 4px 0;">
                        开发者：<a href="https://github.com/zhiyiYo" style="color: #0078d4;">zhiyiYo</a>
                    </p>
                </div>
            </div>
            <div style="margin-top: 16px; padding: 12px; background: #e8f4fd; border-radius: 6px;">
                <p style="font-size: 14px; color: #0078d4; margin: 0; text-align: center;">
                    本项目采用 GPLv3 许可证进行分发
                </p>
            </div>
        </div>
        '''
        
        thanks_label = BodyLabel()
        thanks_label.setText(thanks_html)
        thanks_label.setWordWrap(True)
        thanks_label.setOpenExternalLinks(True)
        thanks_layout.addWidget(thanks_label)
        
        # 项目链接按钮
        links_layout = QHBoxLayout()
        links_layout.setSpacing(12)
        
        pymapgis_btn = PushButton("pymapgis 项目", self)
        pymapgis_btn.setIcon(FIF.LINK)
        pymapgis_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/leecugb/pymapgis")))
        
        fluent_btn = PushButton("PyQt-Fluent-Widgets", self)
        fluent_btn.setIcon(FIF.LINK)
        fluent_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/zhiyiYo/PyQt-Fluent-Widgets")))
        
        links_layout.addWidget(pymapgis_btn)
        links_layout.addWidget(fluent_btn)
        links_layout.addStretch()
        
        thanks_layout.addLayout(links_layout)
        self.thanksCard.viewLayout.addLayout(thanks_layout)





class HomeInterfaceWidget(SingleDirectionScrollArea):
    """主界面滚动区，包含转换配置卡片"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)
        self.settingCard = MapgisConvertConfigWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setObjectName("appInterface")
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.addWidget(self.settingCard, 0, Qt.AlignTop)
        self.vBoxLayout.addStretch()
        self.enableTransparentBackground()


class LogWidget(QWidget):
    """日志输出窗口"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.textEdit = QTextEdit(self)
        self.textEdit.setReadOnly(True)
        # 设置字体为等宽字体，便于阅读日志
        font = self.textEdit.font()
        font.setFamily("Consolas")
        font.setPointSize(10)
        self.textEdit.setFont(font)
        # 设置文本编辑器属性，确保换行符正确处理
        self.textEdit.setLineWrapMode(QTextEdit.NoWrap)  # 禁用自动换行，保持日志格式
        self.textEdit.setAcceptRichText(True)  # 接受富文本格式
        self.layout.addWidget(self.textEdit)
        self.setLayout(self.layout)
        self.setObjectName("logInterface")

    def append_log(self, text):
        """添加日志文本，支持多行文本"""
        # 如果文本包含换行符，按行分割并逐行添加
        if '\n' in text:
            lines = text.split('\n')
            for line in lines:
                if line.strip():  # 只添加非空行
                    self.textEdit.append(line)
        else:
            self.textEdit.append(text)
        
        # 自动滚动到底部
        self.textEdit.verticalScrollBar().setValue(self.textEdit.verticalScrollBar().maximum())
    
    def append_log_with_color(self, text, color=None):
        """带颜色输出日志，支持多行文本"""
        # 如果文本包含换行符，按行分割并逐行添加
        if '\n' in text:
            lines = text.split('\n')
            for line in lines:
                if line.strip():  # 只添加非空行
                    if color:
                        # 使用HTML格式来设置颜色
                        html_text = f'<span style="color: {color};">{line}</span>'
                        self.textEdit.append(html_text)
                    else:
                        self.textEdit.append(line)
        else:
            if color:
                # 使用HTML格式来设置颜色
                html_text = f'<span style="color: {color};">{text}</span>'
                self.textEdit.append(html_text)
            else:
                self.textEdit.append(text)
        
        # 自动滚动到底部
        self.textEdit.verticalScrollBar().setValue(self.textEdit.verticalScrollBar().maximum())


class QTextEditLogger:
    """将print内容输出到QTextEdit的日志流"""
    def __init__(self, text_edit):
        self.text_edit = text_edit
        self.buffer = ""
        self.is_stderr = False
        self._pending_lines = []
        self._timer = None
        self._setup_timer()

    def _setup_timer(self):
        """设置定时器，批量更新UI"""
        from PyQt5.QtCore import QTimer
        self._timer = QTimer()
        self._timer.timeout.connect(self._flush_pending_lines)
        self._timer.start(50)  # 每50ms更新一次，提高响应速度

    def _flush_pending_lines(self):
        """批量刷新待处理的日志行"""
        if self._pending_lines:
            # 逐行添加文本，确保换行符正确处理
            for line in self._pending_lines:
                self.text_edit.append(line)
            
            # 自动滚动到底部
            scrollbar = self.text_edit.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            
            self._pending_lines.clear()

    def write(self, msg):
        msg = str(msg)
        self.buffer += msg
        
        # 当遇到换行符时输出完整的一行
        if '\n' in self.buffer:
            lines = self.buffer.split('\n')
            # 输出完整的行
            for line in lines[:-1]:
                if line.strip():  # 只输出非空行
                    # 根据内容判断是警告还是错误
                    formatted_line, color = self._format_line(line)
                    if formatted_line:
                        # 使用批量更新机制，避免频繁UI更新
                        if color:
                            # 使用HTML格式来设置颜色
                            html_text = f'<span style="color: {color};">{formatted_line}</span>'
                            self._pending_lines.append(html_text)
                        else:
                            self._pending_lines.append(formatted_line)
            # 保留最后一行（可能不完整）
            self.buffer = lines[-1]
        # 如果没有换行符，检查是否应该立即输出（比如错误信息）
        elif self.is_stderr and msg.strip():
            # 对于stderr，立即输出错误信息
            formatted_line, color = self._format_line(msg)
            if formatted_line:
                if color:
                    html_text = f'<span style="color: {color};">{formatted_line}</span>'
                    self._pending_lines.append(html_text)
                else:
                    self._pending_lines.append(formatted_line)

    def flush(self):
        """输出缓冲区中剩余的内容"""
        if self.buffer.strip():
            formatted_line, color = self._format_line(self.buffer)
            if formatted_line:
                if color:
                    html_text = f'<span style="color: {color};">{formatted_line}</span>'
                    self._pending_lines.append(html_text)
                else:
                    self._pending_lines.append(formatted_line)
            self.buffer = ""
    
    def _format_line(self, line):
        """格式化日志行，区分警告和错误，返回格式化的文本和颜色"""
        line = line.strip()
        if not line:
            return "", None
        
        # 过滤掉无意义的INFO日志
        if "Created" in line and "records" in line:
            return "", None
        
        # 检查是否是警告信息
        if self.is_stderr:
            # 常见的警告关键词和模式
            warning_patterns = [
                'warning', 'warn', 'deprecated', 'deprecation', 
                'UserWarning', 'FutureWarning', 'DeprecationWarning',
                'PendingDeprecationWarning', 'RuntimeWarning',
                'SyntaxWarning', 'UnicodeWarning', 'BytesWarning',
                'ResourceWarning', 'ImportWarning'
            ]
            
            # 检查是否包含警告关键词
            is_warning = any(pattern.lower() in line.lower() for pattern in warning_patterns)
            
            # 特殊检查：如果行以冒号开头且包含警告信息，也认为是警告
            if not is_warning and ':' in line:
                parts = line.split(':', 1)
                if len(parts) > 1 and any(pattern.lower() in parts[0].lower() for pattern in warning_patterns):
                    is_warning = True
            
            if is_warning:
                return f"⚠️  [WARNING] {line}", "#FF8C00"  # 橙色
            else:
                return f"🚨  [ERROR] {line}", "#DC143C"   # 红色
        else:
            # 为普通信息添加时间戳和美化
            if line.startswith("✅") or line.startswith("🎉") or line.startswith("📄"):
                return f"🕐 {datetime.now().strftime('%H:%M:%S')} | {line}", "#228B22"  # 绿色
            elif line.startswith("❌"):
                return f"🕐 {datetime.now().strftime('%H:%M:%S')} | {line}", "#DC143C"  # 红色
            elif line.startswith("=") or line.startswith("-"):
                # 分隔线使用特殊颜色
                return line, "#666666"  # 灰色
            elif line.startswith("📋") or line.startswith("📁") or line.startswith("📄") or line.startswith("🔧") or line.startswith("🌍") or line.startswith("📝") or line.startswith("🚀"):
                # 配置信息使用蓝色
                return f"🕐 {datetime.now().strftime('%H:%M:%S')} | {line}", "#0066CC"  # 蓝色
            else:
                return f"🕐 {datetime.now().strftime('%H:%M:%S')} | {line}", "#000000"  # 黑色


class MainWindow(FluentWindow):
    """主窗口，包含导航与各功能页面"""
    def __init__(self):
        super().__init__()
        self.homeInterface = HomeInterfaceWidget(self)
        self.logInterface = LogWidget(self)
        self.aboutInterface = AboutWidget(self)
        
        # 设置日志文本编辑器的颜色格式
        self.setup_log_colors()
        
        # 日志窗口与print联动
        stdout_logger = QTextEditLogger(self.logInterface.textEdit)
        stderr_logger = QTextEditLogger(self.logInterface.textEdit)
        stderr_logger.is_stderr = True
        
        # 在打包环境中，谨慎处理stdout/stderr重定向
        if not getattr(sys, 'frozen', False):
            # 开发环境：完全重定向
            sys.stdout = stdout_logger
            sys.stderr = stderr_logger
            
            # 配置logging模块
            logging.basicConfig(
                level=logging.WARNING,  # 只显示WARNING及以上级别
                format='%(message)s',   # 简化格式，避免时间戳重复
                handlers=[
                    logging.StreamHandler(stderr_logger)
                ]
            )
        else:
            # 打包环境：使用信号机制，避免直接重定向
            self._stdout_logger = stdout_logger
            self._stderr_logger = stderr_logger
            
            # 配置logging模块，使用自定义处理器
            class CustomHandler(logging.Handler):
                def __init__(self, logger):
                    super().__init__()
                    self.logger = logger
                
                def emit(self, record):
                    msg = self.format(record)
                    self.logger.write(msg + '\n')
            
            logging.basicConfig(
                level=logging.WARNING,
                format='%(message)s',
                handlers=[CustomHandler(stderr_logger)]
            )
        self.initNavigation()
        self.initWindow()
        # ========== 新增：捕获所有Python警告到日志窗口 ==========
        def custom_showwarning(message, category, filename, lineno, file=None, line=None):
            warning_msg = warnings.formatwarning(message, category, filename, lineno, line)
            if hasattr(self, 'logInterface'):
                self.logInterface.append_log_with_color(warning_msg, color="#FF8C00")
            else:
                print(warning_msg)
        warnings.showwarning = custom_showwarning
    
    def setup_log_colors(self):
        """设置日志文本编辑器的颜色格式"""
        # 设置文本编辑器的样式表，为不同类型的日志设置颜色
        self.logInterface.textEdit.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: 10pt;
                line-height: 1.2;
                white-space: pre;
            }
        """)

    def initNavigation(self):
        self.addSubInterface(self.homeInterface, FIF.HOME, '转换配置')
        self.addSubInterface(self.logInterface, FIF.BOOK_SHELF, '日志输出')
        self.addSubInterface(self.aboutInterface, FIF.INFO, '软件介绍')

    def initWindow(self):
        self.resize(900, 700)
        self.setWindowIcon(QIcon(get_resource_path('resource/图标.ico')))
        self.setWindowTitle(f'Mapgis转换工具 {VERSION}')
        desktop = QApplication.desktop().availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)


if __name__ == '__main__':
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec_()
