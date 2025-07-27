# ConvertMapGIS

一个基于Python的MapGIS文件转换工具，支持将MapGIS格式文件转换为Shapefile格式。

## 软件界面

### 主界面

![日志界面](https://vip.123pan.cn/1830392062/ymjew503t0n000d7w32y6qzrq1iw0xvtDIYwDdD2DqazDpxPDwJy.png)

### 日志界面
![日志界面](https://vip.123pan.cn/1830392062/yk6baz03t0m000d7w33ga5rqxmls0ptkDIYwDdD2DqazDpxPDwJy.png)


## 项目由来

工作之后，学习了Arcgis的使用，单位老资料普遍是用mapgis6.7做的，想要使用的话就需要先进行转换，查阅后发现目前的转换工具主要如下：

- **map2shp**：一款经典的MapGIS转shapefile的小工具，界面简洁，支持基础的文件转换。  
  **优点**：目前感觉是见过最完美的转换效果，支持把符号都转换过来。  
  **缺点**：价格昂贵，不支持比例转换。

- **FME**：功能强大的商业数据转换平台，支持包括MapGIS在内的多种GIS数据格式转换，适合大规模、复杂数据处理。  
  **优点**：支持自定义传递的字段并重命名。  
  **缺点**：不支持比例转换，价格昂贵，mapgis的支持需要安装插件，插件需要申请，有效期一年。

- **section**：开源的MapGIS数据处理库，支持MapGIS文件的读取和部分转换操作，适合开发者进行二次开发和定制。  
  **优点**：不需要额外装软件。  
  **缺点**：不支持自带属性传递，需要先参数转属性；不支持比例转换。

- **pymapgis**：Python语言实现的MapGIS文件解析与转换库，支持MapGIS到shapefile等格式的转换，易于集成到Python项目中，适合自动化和批量处理场景。  
  **优点**：开源免费，易于脚本化和自动化，支持批量处理，便于自定义修改。  
  **缺点**：字段文本处理有问题，转换效率过慢。


早期时候直接对pymapgis进行修改，新增自带参数的写入，因为单位的mapgis文件有格式各样的问题，新增了直接指定坐标系和比例缩放。原作者对mapgis文件的理解非常透彻，转换的文件矢量坐标和形状与属性没有问题，但是转换的时间特别久，本人不是科班出身，对于优化这块也束手无策。
AI编程逐渐成熟后，尝试用cursor进行优化处理，出乎意料的是效果非常好，于是就全部重构，封装了个UI界面，有了此项目。


### 相对于原项目逻辑有了以下变动：

- 🛠️ 修复部分矢量面转换数量异常问题
- ⚡ 优化面要素节点过多时的转换速度（如：总结点约5000个的面文件，优化前约90秒，优化后约1秒）
- 📏 新增指定缩放比例功能
- 🌐 新增指定坐标系功能
- 🚀 优化原有读取逻辑，大幅提升转换速度（如：一万个点的点文件，优化前约2分钟，优化后约1秒）


## 功能特性

- 🗺️ 支持MapGIS点、线、面要素的转换
- 🔄 批量文件转换功能
- 📏 支持自定义比例尺和坐标系
- 🎨 现代化的PyQt5图形界面
- 📝 详细的转换日志记录


## 使用说明

### 方式一：下载编译好的软件运行

1. 从 [Releases](https://github.com/BenChao1998/ConvertMapGIS/releases) 页面下载最新版本
2. 解压到任意目录
3. 双击运行 `ConvertMapGIS.exe`

### 方式二：本地Python环境运行

#### 环境要求
- Python 3.7+
- Windows/Linux/macOS

#### 安装步骤

1. 克隆项目
```bash
git clone https://github.com/BenChao1998/ConvertMapGIS.git
cd ConvertMapGIS
```

2. 创建虚拟环境（推荐）
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
```

3. 安装依赖
```bash
pip install -r requirements.txt
```
4.运行程序
```bash
python main.py
```


### 命令行使用

#### 基本用法
```python
from pymapgis import MapGisReader

# 读取MapGIS文件
reader = MapGisReader('your_file.wp', scale_factor=1000)

# 转换为Shapefile
reader.to_file('output.shp', encoding='gb18030')
```

#### MapGisReader 类详解

**构造函数参数：**
- `filepath` (str): MapGIS文件路径
- `scale_factor` (int, 可选): 缩放比例，如1000表示1:1000比例尺
- `wkid` (int, 可选): 投影坐标系WKID，如4326表示WGS84

**支持的文件类型：**
- `.wp` - 点要素文件
- `.wl` - 线要素文件  
- `.wt` - 面要素文件

**主要方法：**
- `to_file(filepath, **kwargs)`: 导出为Shapefile格式
- `__len__()`: 获取要素数量
- `__str__()`: 获取文件信息

#### 使用示例

**1. 基本转换**
```python
from pymapgis import MapGisReader

# 读取点要素文件
reader = MapGisReader('points.wp')
reader.to_file('points.shp', encoding='gb18030')
```

**2. 指定坐标系**
```python
# 使用缩放比例
reader = MapGisReader('lines.wl', scale_factor=5000)  # 1:5000比例尺
reader.to_file('lines.shp')

# 使用投影坐标系
reader = MapGisReader('polygons.wt', wkid=4326)  # WGS84坐标系
reader.to_file('polygons.shp')
```

**3. 批量转换**
```python
import os
from pymapgis import MapGisReader

mapgis_files = ['file1.wp', 'file2.wl', 'file3.wt']
output_dir = 'output'

for file in mapgis_files:
    if os.path.exists(file):
        reader = MapGisReader(file, scale_factor=1000)
        output_file = os.path.join(output_dir, f"{os.path.splitext(file)[0]}.shp")
        reader.to_file(output_file, encoding='gb18030')
        print(f"转换完成: {file} -> {output_file}")
```

**4. 上下文管理器使用**
```python
with MapGisReader('data.wp', scale_factor=1000) as reader:
    reader.to_file('data.shp', encoding='gb18030')
    print(f"要素数量: {len(reader)}")
```

## 项目结构

```
ConvertMapGIS/
├── main.py              # 主程序入口（PyQt5 + QFluentWidgets GUI）
├── pymapgis.py          # 核心转换库
├── requirements.txt     # 项目依赖
├── README.md           # 项目说明
└── resource/           # 资源文件
    ├── *.png          # 界面图标
    └── *.svg          # 矢量图标
```
## 常见问题

### Q: 转换报错，提示数量不一致
A: 在section中，所有文件编辑状态下，右键-压缩保存工程，重新转换

### Q: 指定坐标系时，wkid怎么获取？
A: 常见wkid[查询地址](https://blog.csdn.net/KK_bluebule/article/details/107334734)。

### Q: 指定坐标系时是怎么意思？
A:为当前转换后的文件直接写入坐标系，等同于Arcgis中定义投影。

## 许可证

本项目采用 [GPLv3](LICENSE) 许可证进行分发。

## 致谢

- 基于 [pymapgis](https://github.com/leecugb/pymapgis) 项目进行开发
- 感谢原作者 [leecugb](https://www.zhihu.com/people/cugb-93/posts) 的贡献
- 使用 [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) 构建现代化界面
- 感谢 [zhiyiYo](https://github.com/zhiyiYo) 开发的优秀UI组件库

[![pymapgis](https://github-readme-stats.vercel.app/api/pin/?username=leecugb&repo=pymapgis)](https://github.com/leecugb/pymapgis)
[![PyQt-Fluent-Widgets](https://github-readme-stats.vercel.app/api/pin/?username=zhiyiYo&repo=PyQt-Fluent-Widgets)](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)

