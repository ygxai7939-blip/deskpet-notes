# 桌宠便签 · DeskPet Notes

一款中文 Windows 桌面应用，把可换角色的桌宠和可吸附屏幕边缘的便签放在一起。便签、角色和设置保存在本机。

发布者 **Ygxai**。Windows 安装包见 [GitHub Releases](https://github.com/ygxai7939-blip/deskpet-notes/releases)。

- 双击桌宠打开便签库，右键可新建便签或调整桌宠设置。
- 拖动便签到屏幕边缘即可贴边，点击边缘标签展开或收起。支持搜索、清单勾选、归档和批量删除。
- 支持导入多个角色 ZIP，在「桌宠设置 → 我的桌宠」点卡片切换当前角色。导入时可预览，遇到相同 ID 可更新或另存。
- 桌宠可接住用鼠标中键拖来的纸团。便签库的背景使用单色像素雪。

## 从源码运行

需要 64 位 Windows 10（版本 2004 或更新）或 Windows 11，以及带有 `py` 启动器的 Python 3.12 x64。克隆仓库后，在根目录打开 PowerShell 运行以下命令。

```powershell
py -3.12 -m venv .\work\venv
.\work\venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\work\venv\Scripts\python.exe .\work\release\prepare_assets.py --kit-only
.\work\venv\Scripts\python.exe .\work\deskpet-live\open_preview.pyw
```

首次运行时，可在「桌宠设置 → 导入角色 ZIP」选择[示例角色](work/release/example.codex-pet.zip)。

## 制作自己的小宠物

在「桌宠设置」点击「导出角色工具包」。把工具包和参考图交给 Codex，再复制[小宠物制作指令](work/release/小宠物制作指令.md)里的提示词。拿到角色 ZIP 后，在软件里预览并导入。图集和打包格式见[角色制作说明](work/release/角色制作说明.md)。

## 构建安装包

安装 [Inno Setup 6.7](https://jrsoftware.org/isinfo.php)，然后在仓库根目录运行下列命令。如果 Inno Setup 装在其他目录，请把最后一行的路径改成实际的 `ISCC.exe` 路径。

```powershell
.\work\venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath .\work\release\dist --workpath .\work\release\build .\work\release\DeskPetNotes.spec
.\work\venv\Scripts\python.exe .\work\release\prepare_assets.py
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" .\work\release\DeskPetNotes.iss
```

安装包生成在 `outputs/DeskPetNotes-Setup-1.1.1.exe`。如需运行界面冒烟测试，可以执行 `.\work\venv\Scripts\python.exe .\work\deskpet-live\verify_notes.py`。测试使用临时目录及仓库内的示例角色。

## 许可证

1.1.1 的完整发行版和 Ygxai 有权授权的新增内容按 [PolyForm Noncommercial 1.0.0](LICENSE) 提供，仅限非商业用途。商用须获得 Ygxai 的另行授权。适用范围见 [NOTICE](NOTICE)。

第三方组件继续适用[原许可证](work/release/第三方许可.md)，已经按 [Apache-2.0 发布的 1.1.0](https://github.com/ygxai7939-blip/deskpet-notes/blob/v1.1.0/LICENSE) 也继续适用原条款。用户导入的角色素材由其创作者或权利人决定使用条件。
