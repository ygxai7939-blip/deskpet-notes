# 桌宠便签 · DeskPet Notes

一款中文 Windows 桌面应用，把可换角色的桌宠和可吸附屏幕边缘的便签放在一起。便签、角色和设置保存在本机。

发布者 **Ygxai**。Windows 安装包见 [GitHub Releases](https://github.com/ygxai7939-blip/deskpet-notes/releases)。

- 双击桌宠打开便签库，右键可新建便签或调整桌宠设置。
- 单击触发回应，鼠标在头部来回移动可以摸头，按住拖动可提起和放下宠物。勾完一张便签里的清单时，宠物会庆祝。
- 拖动便签到屏幕边缘即可贴边，点击边缘标签展开或收起。支持搜索、清单勾选、归档和批量删除。
- 托盘菜单中的「收起便签」会隐藏全部桌面便签和贴边标签。单张便签菜单里的同名操作只收起当前便签，之后可从便签库重新打开。
- 多张便签贴边时，按住标签栏底部的「＋」向上压紧、向下展开，松开后保留高度。点击「＋」可新建便签。
- 便签的「··· → 编辑标签」可添加或移除多个标签。便签库支持按标签和状态组合筛选，也可以搜索标题、正文或标签。
- 支持导入多个角色 ZIP，在「桌宠设置 → 我的桌宠」点卡片切换当前角色。导入时可预览，遇到相同 ID 可更新或另存。
- 角色卡片右上角的「…」可预览角色自带的动作或删除角色。删除当前角色时优先切到后面最近可用的角色，再找前面的角色。确认框会显示切换结果。
- 在「桌宠设置 → 备份与恢复」把便签、角色和设置导出为一个 ZIP。还原前会显示备份日期和数量，并自动保存还原前的数据。
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

## 备份与恢复

在「桌宠设置」的「行为设置」下方点击「导出备份」，把带日期的 ZIP 存到你选的文件夹。这个 ZIP 包含普通及归档便签、正文格式和勾选状态、已安装的角色、当前角色和常用设置。

在新电脑上安装支持备份的版本，点击「从备份还原」。确认前可以查看日期、便签数和角色数。软件会先把现有数据保存在 `%LOCALAPPDATA%\DeskPetNotes\backups`，再整套替换为备份中的数据。备份中含有扩展格式角色时，请用 1.2.0 或以上版本还原。

## 制作自己的小宠物

在「桌宠设置」点击「导出角色工具包」。把工具包和参考图交给 Codex，再复制[小宠物制作指令](work/release/小宠物制作指令.md)里的提示词。拿到角色 ZIP 后，在软件里预览并导入。图集和打包格式见[角色制作说明](work/release/角色制作说明.md)。

## 构建安装包

安装 [Inno Setup 6.7](https://jrsoftware.org/isinfo.php)，然后在仓库根目录运行下列命令。如果 Inno Setup 装在其他目录，请把最后一行的路径改成实际的 `ISCC.exe` 路径。

```powershell
.\work\venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath .\work\release\dist --workpath .\work\release\build .\work\release\DeskPetNotes.spec
.\work\venv\Scripts\python.exe .\work\release\prepare_assets.py
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" .\work\release\DeskPetNotes.iss
```

安装包生成在 `outputs/DeskPetNotes-Setup-1.2.2.exe`。如需运行界面冒烟测试，可以执行 `.\work\venv\Scripts\python.exe .\work\deskpet-live\verify_notes.py`。测试使用临时目录及仓库内的示例角色。

## 许可证

从 1.1.1 起，完整发行版和 Ygxai 有权授权的新增内容按 [PolyForm Noncommercial 1.0.0](LICENSE) 提供，仅限非商业用途。商用须获得 Ygxai 的另行授权。适用范围见 [NOTICE](NOTICE)。

第三方组件继续适用[原许可证](work/release/第三方许可.md)。已经按 [Apache-2.0](LICENSE-APACHE-2.0.txt) 发布的历史代码继续适用原条款。用户导入的角色素材由其创作者或权利人决定使用条件。
