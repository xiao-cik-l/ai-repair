# 容器化部署说明

这份文档只讲一件事：怎么用 Docker 把这个项目连同数据库一起跑起来，以及出问题时怎么查。
不装 Docker 也能跑，见 README 第三节的手动流程。

---

## 一、先装 Docker（这台机器务必先看这一节）

当前机器的实际情况：Windows 11 版本 26200，CPU 4 核 8 线程，物理内存 7.71GB，
C 盘剩余 66GB，WSL 与 Docker 都还没装。

内存是唯一需要认真对待的约束。Docker Desktop 在 Windows 上并不直接跑容器，
它先起一个 WSL2 虚拟机，容器跑在虚拟机里，而 WSL2 默认会拿走物理内存的一半，
也就是接近 4GB。实测当前可用内存只有 0.4GB 左右（WorkBuddy 1.8GB、系统服务 1.3GB、
浏览器合计约 2GB），按默认配置一启动容器就会内存不足，严重时整机卡死。

所以顺序不能错，先限制配额，再装 Docker。

第一步，用管理员身份打开 PowerShell，执行：

```
wsl --install --no-distribution
```

这一步会打开「虚拟机平台」和「适用于 Linux 的 Windows 子系统」两个功能，装完必须重启。
只用 Docker 的话不需要装 Ubuntu 等发行版，加 `--no-distribution` 就够。

第二步，重启后确认虚拟化已生效：

```
wsl --status
```

第三步，下载并安装 Docker Desktop for Windows，安装时保持默认选项。
装完首次启动会要求接受协议，选默认设置即可。

第四步，也是最关键的一步，先在用户目录下建好配置文件再启动 Docker。
新建 `C:\Users\lenovo\.wslconfig`，内容如下：

```
[wsl2]
memory=2GB
processors=4
swap=2GB
localhostForwarding=true
```

这个文件决定虚拟机能用多少内存。压到 2GB 是本项目能跑起来的前提，
不写这个文件，后面所有优化都没有意义。改完执行 `wsl --shutdown` 让它重新生效。

装完之后建议在 Docker Desktop 的 Settings 里再确认两项：Resources 里内存显示为 2GB；
General 里不要勾选「Start Docker Desktop when you sign in」，避免开机就吃掉内存。

一个可以接受的副作用：WSL2 打开虚拟化平台后，个别带反作弊的游戏可能启动失败。
真遇到就执行 `wsl --shutdown` 把虚拟机停掉，不影响任何数据，也不影响项目文件。

---

## 二、三步启动

第一步，准备配置文件。在项目根目录执行：

```
cp .env.docker.example .env
```

然后编辑 .env，至少填三项：`MYSQL_ROOT_PASSWORD` 设一个自己的密码，
`DASHSCOPE_API_KEY` 填百炼的 Key，`SMTP_USER` 和 `SMTP_PASSWORD` 填发验证码的 QQ 邮箱与授权码。
不填邮箱又想演示登录，就把 `DEMO_LOGIN_CODE` 改成 1，验证码会打印在日志里，不发真邮件。

第二步，构建并启动：

```
docker compose up -d --build
```

首次构建要装依赖，4 核机器大约 5 到 10 分钟，主要时间花在 chromadb 和 onnxruntime 上。
第二次起有层缓存，改代码再构建通常十几秒。

第三步，看启动日志，等出现 `[entrypoint] 启动 gunicorn` 就绪：

```
docker compose logs -f web
```

然后浏览器打开 http://localhost:5000

---

## 三、起来之后怎么验

日志里应该依次出现这几行，每一行对应一个启动阶段，缺哪一行就知道卡在哪：

```
[entrypoint] 等待 MySQL db:3306 ...
[entrypoint] MySQL 已就绪
[entrypoint] 表结构已存在，跳过建表        （首次是「已按 schema_mysql.sql 建表」）
[entrypoint] 初始化演示账号 ...
[entrypoint] 向量库已存在，跳过灌库
[entrypoint] 启动 gunicorn 0.0.0.0:5000 ...
```

页面验证按这个顺序，能一路走通说明四层都通了：

1. 打开首页能显示登录页 —— 说明 Flask 与静态资源正常
2. 用学生账号登录，邮箱填 .env 里 `SMTP_USER` 的值 —— 说明 MySQL 连上了、账号建对了、邮件发出去了
3. 登录后自动进入 AI 助手页，问一句「空调不制冷怎么办」—— 说明向量库和大模型 Key 都正常
4. 接着说「帮我报修，3 号楼 305」—— 说明工具调用和写库正常，去工单列表能看到新单

第 2 步如果没配邮箱，用 `DEMO_LOGIN_CODE=1`：点发送验证码后执行
`docker compose logs -f web | grep 验证码`，能看到形如 `[演示模式] 未配置 SMTP 授权码，
验证码不真实发信：xxx@xx.com -> 483920` 的一行。

---

## 四、内存账

WSL 虚拟机限制在 2GB，项目内部再按服务分配上限，合计不超过 1.1GB：

应用容器（web）上限 620MB，实际占用比 Flask 开发服务器略高，因为 gunicorn 起了一个主进程
加一个工作进程。数据库容器（db）上限 480MB，靠 mysql-low-mem.cnf 把 buffer pool 压到 64MB、
关掉 performance_schema 才压得下来，默认配置要 500MB 以上。

2GB 里 Linux 系统本身占约 450MB，MySQL 约 350MB，应用约 150MB，剩下 1GB 左右是余量。
这个余量不能省，chromadb 首次加载 onnxruntime 时会有一个内存尖峰，没有余量就会在第一次问答时被 OOM 杀掉。

想更省可以把 `WEB_WORKERS` 保持为 1，线程数 8 已经够演示用。
不要为了「看起来更专业」把 worker 调到 4，每个 worker 都是一份完整的 Python 进程，
本机内存扛不住。

---

## 五、常见报错

端口被占用。报错里出现 `bind: address already in use` 或 `port is already allocated`。
说明 5000 端口被别的程序占了，改 .env 里 `WEB_PORT=5001` 后重新 `docker compose up -d`。

连不上数据库，日志停在「等待 MySQL」。多半是数据卷里存着上一次的旧密码，
而 .env 里的 `MYSQL_ROOT_PASSWORD` 已经改过。MySQL 的 root 密码只在数据卷首次初始化时写入，
之后改 .env 不生效。解决办法是 `docker compose down -v` 清掉数据卷重建，
注意这会删掉已有工单数据。也可以改回原来的密码。

`Access denied for user 'root'`。同上，密码与数据卷不一致。

提示某张表不存在。正常不该出现，因为启动脚本会自检并补建。如果真出现，
先看日志里「检查表结构」那一步有没有报错，再确认 `schema_mysql.sql` 是否在项目根目录。

`ImportError: libgomp.so.1: cannot open shared object file`。这是 onnxruntime 的运行时依赖，
Dockerfile 里已经装了 libgomp1。如果自己换基础镜像（比如换成 alpine），需要把这个包装回去。

AI 助手返回 403 或额度不足。和容器无关，是模型名或额度问题。
百炼的免费额度按「模型快照」独立发放，写别名 `deepseek-v4-pro` 会 403，
必须写快照全名 `deepseek-v4-pro-0813`。改 .env 里的 `LLM_MODEL` 后重启容器即可，改代码没用。

登录一直提示验证码错误。检查 `SMTP_USER` 与数据库里账号的邮箱是否一致。
登录会同时校验学号和邮箱，两处不一致就查不到用户，报错信息却只提示「学号、邮箱或密码错误」。

---

## 六、数据放哪了，怎么重置

MySQL 数据在名为 `dorm-repair_mysql_data` 的卷里，维修结果图片在 `dorm-repair_uploads` 卷里。
容器删了重建，这两份数据都还在。

查看卷：`docker volume ls`
备份数据库：`docker exec dorm-mysql mysqldump -uroot -p你的密码 cjl_505 > backup.sql`
彻底重置（连库带图一起删，谨慎）：

```
docker compose down -v
docker compose up -d
```

只重启不重建：`docker compose restart web`。改了代码要重新构建：`docker compose up -d --build`。

---

## 七、和本地运行的关系

两种跑法用的是同一份代码，差异只在环境变量，不需要维护两套代码。

唯一改过的代码是入口：`app.py` 原来写死 `host="127.0.0.1", port=5000, debug=True`，
现在读 `FLASK_RUN_HOST`、`FLASK_RUN_PORT`、`FLASK_DEBUG` 三个环境变量，默认值就是原来的值，
所以本地 `python app.py` 的行为完全不变。

容器里不用 `python app.py`，用 gunicorn 起服务，并且用 gthread 工作模式而不是默认的 sync。
原因是 AI 回答走 SSE 分块推送，一条流会占用连接较久，sync 模式下单个 worker 会被这条流堵住，
后续请求只能排队。

---

## 八、还没做的部分

镜像没有推到镜像仓库，别人仍需自己构建。生产部署还缺反向代理和 HTTPS、
多副本与负载均衡、日志收集。这些不属于本项目当前范围，写在这里是为了答辩被问到时能说清边界。
