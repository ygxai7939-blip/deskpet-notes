# 桌宠便签 · DeskPet Notes

一款中文 Windows 桌面应用，把可换角色的桌宠和可吸附屏幕边缘的便签放在一起。1.1.0 的便签和设置保存在本机。

- 双击桌宠打开便签库，右键可新建便签或调整桌宠设置。
- 拖动便签到屏幕边缘即可贴边，点击边缘标签展开或收起。支持搜索、清单勾选、归档和批量删除。
- 支持导入和更新角色 ZIP。角色包可在安装前预览。
- 桌宠可接住用鼠标中键拖来的纸团。便签库的背景使用单色像素雪。

## 从源码运行

需要 64 位 Windows 10（版本 2004 或更新）或 Windows 11，以及带有 `py` 启动器的 Python 3.12 x64。克隆仓库后，在根目录打开 PowerShell 运行以下命令。

```powershell
py -3.12 -m venv .\work\venv
.\work\venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\work\venv\Scripts\python.exe .\work\release\prepare_assets.py --kit-only
.\work\venv\Scripts\python.exe .\work\deskpet-live\open_preview.pyw
```

首次运行时，可在「桌宠设置 → 导入角色 ZIP」选择 [示例角色](work/release/example.codex-pet.zip)。也可以在该页面导出角色制作工具包，交给 Codex 制作或整理自己的素材。[角色制作说明](work/release/角色制作说明.md)介绍了图集、动作和打包格式。

## 构建安装包

安装 [Inno Setup 6.7](https://jrsoftware.org/isinfo.php)，然后在仓库根目录运行下列命令。如果 Inno Setup 装在其他目录，请把最后一行的路径改成实际的 `ISCC.exe` 路径。

```powershell
.\work\venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath .\work\release\dist --workpath .\work\release\build .\work\release\DeskPetNotes.spec
.\work\venv\Scripts\python.exe .\work\release\prepare_assets.py
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" .\work\release\DeskPetNotes.iss
```

安装包生成在 `outputs/DeskPetNotes-Setup-1.1.0.exe`。如需运行界面冒烟测试，可以执行 `.\work\venv\Scripts\python.exe .\work\deskpet-live\verify_notes.py`。测试使用临时目录及仓库内的示例角色。

## 许可证

本项目新增源码和示例素材按 [Apache-2.0](LICENSE) 发布。DeskPet 底座、DeskStickyNotes 以及安装器翻译的版权与许可保留在各自目录，详见[第三方许可](work/release/第三方许可.md)。用户导入的角色素材由其创作者或权利人决定使用条件。
