# 江西职教云实习平台自动签到脚本

这是一个用于江西职教云自主实习签到的自动化脚本，当前实现已经和真实平台链路对齐。

## 当前状态

- 旧的 `/portal-api/app/index/login` 账号密码直登接口已不再作为可用主链路
- 当前真实可用方案是：
  - 浏览器完成统一认证登录
  - 获取 `app_user_id`
  - 再调用 `checkAppUserIdNew` 换签到 Bearer token
- 脚本已经支持“一次绑定，后续自动换 token”

## 主要功能

- 支持 `--bind-account` 打开浏览器完成统一认证绑定
- 支持自动保存地址、GCJ-02 经纬度、默认图、早图、晚图
- 支持 token 缓存优先，失效后自动重新绑定
- 支持上传图片后轮询校验，再提交签到
- 支持多账号
- 支持常驻定时模式和单次执行模式
- 支持晚上只有 1 条记录时补签到第 2 次
- 支持晚上 0 条记录时自动连签两次：先早图，间隔 10 秒后晚图
- 支持立即执行常驻模式同款任务，便于不等定时点测试

## 安装依赖

```powershell
python -m pip install requests schedule pytest playwright selenium
```

如果要优先使用 Playwright，还需要额外安装浏览器驱动：

```powershell
python -m playwright install
```

如果 Playwright 在本机不可用，脚本会自动回退到 Selenium + 系统 Edge/Chrome。

## 常用命令

### Windows EXE 版

`win` 分支已提供打包好的 Windows 可执行文件：

- [下载 jiangzhi-checkin.exe](https://github.com/qiuridong/-1/raw/win/dist/jiangzhi-checkin.exe)
- [下载 checkin_config.example.json](https://raw.githubusercontent.com/qiuridong/-1/win/checkin_config.example.json)

EXE 版不需要安装 Python，也不需要执行 `python -m playwright install`。它使用本机已安装的 Edge 或 Chrome 完成浏览器授权。

国内服务器首次绑定时，默认不要再依赖 `nominatim.openstreetmap.org`。当前版本已经支持在本地配置里填写高德 Key：

```json
{
  "amap_key": ""
}
```

说明：

- GitHub 仓库里的默认配置项只保留空字符串，不会提交真实 Key
- 你需要在自己机器上的 `checkin_config.json` 里填写真实 `amap_key`
- 如果 `amap_key` 为空，脚本才会回退到旧的 Nominatim 地址解析；该服务在国内服务器上通常不稳定
- `checkin_config.json` 和 `token.json` 建议与 `jiangzhi-checkin.exe` 一起部署

如果本地还没有 `checkin_config.json`，有两种办法：

1. 直接复制模板
   - 把 `checkin_config.example.json` 改名为 `checkin_config.json`
2. 让程序自动生成
   - 运行 `.\jiangzhi-checkin.exe --init-config`

最少需要手动填写的配置通常是：

- `amap_key`
- `clock_address`
- `proof_image_path`
- `proof_images.morning`
- `proof_images.evening`
首次绑定：

```powershell
.\jiangzhi-checkin.exe --bind-account
```

只测试链路，不真正提交：

```powershell
.\jiangzhi-checkin.exe --once --dry-run
```

真实签到一次：

```powershell
.\jiangzhi-checkin.exe --once
```

立即执行常驻模式同款晚上任务：

```powershell
.\jiangzhi-checkin.exe --run-scheduled-slot-now evening
```

常驻定时运行：

```powershell
.\jiangzhi-checkin.exe
```

说明：如果 `checkin_config.json` 不在 EXE 同目录，请加 `--config 配置文件路径`。

### Python 版
首次绑定或重新绑定：

```powershell
python auto_checkin.py --bind-account
```

只执行一次真实签到：

```powershell
python auto_checkin.py --once
```

只测试链路，不真正提交：

```powershell
python auto_checkin.py --once --dry-run
```

强制签到一次：

```powershell
python auto_checkin.py --once --force
```

启动常驻模式：

```powershell
python auto_checkin.py
```

如果当天记录为 `0` 条，晚间同款任务会自动先用早图签到一次，等待 `10` 秒，再用晚图签到一次。

查看帮助：

```powershell
python auto_checkin.py --help
```

## 说明

- 绑定流程会先提示输入签到地址和图片路径，最后才打开浏览器登录
- 地址会自动解析成脚本需要的 GCJ-02 经纬度
- 如果 token 在读接口还能用、但写接口返回 `401`，脚本会自动重新换 token 并重试一次
- 提交到 GitHub 的源码已脱敏，真实账号、token、地址和图片路径应只保存在本地 `checkin_config.json` / `token.json`
- 不要提交 `checkin_config.json`、`token.json`、`checkin.log`、缓存目录或个人图片

## 开发与验证

测试命令：

```powershell
python -m pytest test_auto_checkin.py -q
```

更多本地同步和 GitHub 提交说明见：

- [江智签到.md](./江智签到.md)

## 声明

仅供学习和交流使用。
