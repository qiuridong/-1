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

立即执行常驻模式同款晚上任务：

```powershell
python auto_checkin.py --run-scheduled-slot-now evening
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
