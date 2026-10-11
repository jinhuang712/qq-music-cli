# 曲库整理的常见做法

每种做法都按同一套流程走，会改动账号的步骤标了 **（写入）**：

1. 用 `qqmusic export` 或 `qqmusic show` 读取现状。
2. 在本地分析。
3. 把方案给用户看，附上数量和例子。
4. 等用户确认。
5. 用 `--dry-run` 预演一遍。
6. **（写入）** 正式执行。
7. 检查结果字段，把 `run_id` 告诉用户。

下面的 `jq` 查询都在真实的导出文件上跑过。`$F` 指 `qqmusic export` 生成的文件路径，例如 `F=$(qqmusic export | jq -r .path)`。

## 1. 曲库体检（只读）

用户想知道自己曲库的状况，或者想清理一下时，先做这一步。

```sh
F=$(qqmusic export | jq -r .path)

# 同时出现在多个自建歌单里的歌（不算「我喜欢」）
jq '[.playlists[] | select(.dir_id != 201) | .name as $p | .songs[] | {id, name, artist, p: $p}]
    | group_by(.id) | map(select(length > 1))' "$F"

# 「我喜欢」里还没进任何其他歌单的歌，也就是「未整理」的歌
jq '([.playlists[] | select(.dir_id != 201) | .songs[].id] | unique) as $placed
    | [.playlists[] | select(.dir_id == 201) | .songs[] | select(.id as $i | $placed | index($i) | not)]' "$F"

# 同一首歌的多个版本（歌名和歌手相同，id 不同）
jq '[.playlists[].songs[]] | unique_by(.id) | group_by([(.name | ascii_downcase), .artist])
    | map(select(length > 1))' "$F"

# 空歌单和歌很少的歌单
jq '[.playlists[] | {name, n: (.songs | length)}] | sort_by(.n) | .[:5]' "$F"

# 两个歌单的重合部分
jq '[.playlists[] | select(.name == "RNB") | .songs[].id] as $a
    | [.playlists[] | select(.name == "Chill") | .songs[].id] as $b
    | {both: ([$a[] | select(. as $x | $b | index($x))] | length)}' "$F"
```

把发现的问题整理成一张简短的表：每类问题写数量，再举几个例子。用户选好要处理哪些之前，什么都不要改。

## 2. 把「我喜欢」整理成主题歌单

典型说法：「按语种、流派、心情或年代整理我喜欢的歌」。最终结果是一组新歌单，「我喜欢」里的歌被**复制**进去。绝不能从「我喜欢」里删歌。

1. 导出曲库，再选定分类依据：
   - **语种**：用 `language` 代码（见 concepts.md），成本低，结果也准。
   - **流派**：用 `genre` 代码。很多歌的代码是 0（未知），对这些歌用 `qqmusic song --stdin --detail` 分批补查，每批 50 首左右；也可以按歌手来归类。
   - **年代**：用 `release_date`，例如 `select((.release_date // "") >= "2020")`。
   - **心情、场景或活动**（通勤、运动、深夜、下雨天）：根据歌名、歌手、专辑和流派自己判断。实在拿不准的少数歌，用 `qqmusic lyrics` 看看歌词。
2. 和用户商量好分类，并约定下面几点：
   - 分类不超过 15 个。
   - 歌单名不超过 20 个字。
   - 已有同名歌单的，直接沿用。
   - 拿不准的歌放进「待整理」歌单，不要硬猜。
   - 一首歌能不能进多个歌单，最多进 3 个。
3. 给用户看方案：每个目标歌单一行，写明歌曲数量，再举 3 首例子；另外说明「待整理」里有多少首。
4. **（写入）** 每个分类运行一次 `qqmusic create "<歌单名>"`。歌单名已存在时，它会直接返回已有的歌单。
5. **（写入）** 用管道把歌曲 id 传进去。每条命令都先加 `--dry-run` 跑一遍。

   ```sh
   jq -c '[.playlists[] | select(.dir_id == 201) | .songs[] | select(.language == 1) | {id, type}]' "$F" \
     | qqmusic add "粤语" --stdin
   ```

6. 按歌单汇总 `added` 和 `already_present`，如果有 `missing_after_write` 要报出来，最后列出所有 `run_id`。

想先快速看看各语种各有多少首：

```sh
jq '{"0":"国语","1":"粤语","3":"日语","4":"韩语","5":"英语","9":"纯音乐"} as $L
    | [.playlists[] | select(.dir_id == 201) | .songs[] | ($L[(.language|tostring)] // "其他")]
    | group_by(.) | map({lang: .[0], n: length})' "$F"
```

## 3. 根据一句描述生成歌单

典型说法：「做一个下雨天听的华语 R&B 歌单，30 首左右」。

1. 把描述拆成 3 到 6 个搜索词：歌手名、你知道合适的歌名、流派词。逐个运行 `qqmusic search "<搜索词>" --limit 20 --fields +release_date`。
   - 描述里提到节奏（跑步、助眠、慢歌）时，加上 `bpm`：`--fields +release_date,bpm`。很多歌没有 `bpm`，没有的不要直接排除，按歌名和歌手判断。
2. 还可以从用户自己的口味里找歌：「我喜欢」或相关歌单里符合描述的歌。把用户熟悉的歌和新歌混在一起，通常比只用搜索结果效果好。
3. 筛一遍候选：
   - 去掉重复的版本。除非用户想要现场版，否则留录音室版。
   - 去掉伴奏和 K 歌版。
   - 数量控制在用户要求的范围内。
4. 把歌单列给用户看（歌名、歌手、专辑），让用户划掉不想要的。
5. **（写入）** 新建歌单，再把歌加进去：

   ```sh
   qqmusic create "<歌单名>"
   printf '%s\n' <id> <id> ... | qqmusic add "<歌单名>" --stdin
   ```

## 4. 合并、拆分、复制歌单

- **合并**：源歌单保持不变，重复的歌 `add` 会自动去掉。

  ```sh
  qqmusic create "驾驶精选"
  qqmusic show "通勤" --fields id,type | qqmusic add "驾驶精选" --stdin
  qqmusic show "开车" --fields id,type | qqmusic add "驾驶精选" --stdin
  ```

- **拆分**：读出源歌单，按第 2 节的办法给每首歌分组，新建目标歌单，再把各组的歌分别加进去。除非用户要求清空，否则源歌单保持不变。
- **把收藏的歌单或别人的公开歌单复制成自己的**：`tid` 可以从 `qqmusic faved playlists` 里找，也可以从分享链接 `…/playlist/<tid>` 里取。

  ```sh
  qqmusic create "<歌单名>"
  qqmusic show <tid> --fields id,type | qqmusic add "<歌单名>" --stdin
  ```

- **把整张专辑加进歌单**：专辑 mid 从 `qqmusic search "<专辑名>" --type album` 或歌曲的 `album.mid` 里找。

  ```sh
  qqmusic album <专辑 mid> --fields id,type | qqmusic add "<歌单名>" --stdin
  ```

- **改名、改简介**：**（写入）** `qqmusic edit "<歌单名>" --name "<新名字>" --desc "<新简介>"`。`tid` 不变，封面、标签、是否公开都保持原样，`qqmusic undo <run_id>` 可以改回去。

## 5. 去重

- **同一首歌出现在多个歌单里**：这往往是用户有意为之，比如一首歌既在「RAP」里又在「通勤」里。把这些情况列出来，问过用户再删。
- **同一个歌单里有同一首歌的多个版本**：

  ```sh
  jq '[.playlists[] | select(.name == "RNB") | .songs[]]
      | group_by([(.name | ascii_downcase | sub(" *\\(.*\\)$"; "")), .artist])
      | map(select(length > 1) | map({id, name, album: .album.name, release_date}))' "$F"
  ```

  建议保留哪个版本：录音室版优先于现场版，原专辑优先于合辑。**（写入）** 用户同意后运行 `qqmusic remove "<歌单名>" <id...>`。

## 6. 按规则同步歌单

典型说法：「把我喜欢里 Post Malone 的歌都放进 RAP」，或者「每周把新加红心的英文歌同步到英文精选」。

```sh
jq -c '([.playlists[] | select(.name == "RAP") | .songs[].id]) as $have
       | [.playlists[] | select(.dir_id == 201) | .songs[]
          | select(.artist | test("Post Malone")) | select(.id as $i | $have | index($i) | not) | {id, type}]' "$F" \
  | qqmusic add "RAP" --stdin --dry-run
```

- 只补还没加进去的歌。
- 歌单里有些歌已经不符合规则了，删之前要得到用户明确同意，因为那些可能是用户自己手动加的。

## 7. 只整理新加红心的歌

保留上一次的导出文件，再导出一次，只处理两次之间新增的部分：

```sh
jq -n --slurpfile old "$OLD" --slurpfile new "$NEW" '
  ($old[0].playlists[] | select(.dir_id == 201) | [.songs[].id]) as $o
  | [$new[0].playlists[] | select(.dir_id == 201) | .songs[] | select(.id as $i | $o | index($i) | not)
     | {id, type, name, artist}]'
```

然后对这些歌按第 2 节的做法继续整理。从「我喜欢」里消失的歌，只报告给用户，不做任何处理。

## 8. 备份与历史

- `qqmusic export --out <目录>` 会生成 `library-<时间戳>.json`，里面是完整的快照：每个自建歌单和其中的全部歌曲，加上收藏的歌单和专辑。大规模整理之前，建议先导出一份。
- `qqmusic runs` 列出最近的写操作，`qqmusic undo <run_id>` 撤销其中一次。撤销本身也会记成一次 run，所以撤销也能再撤销。

## 9. 清理

- 找出空歌单、歌很少的歌单，以及很久没更新的歌单。`qqmusic playlists` 里的 `updated_at` 是 Unix 时间戳，单位是秒。
- 把候选列给用户，只删除用户点名的：`qqmusic delete "<歌单名>" --yes`。顺便告诉用户，`undo` 能把删掉的歌单连同里面的歌一起恢复，但 `tid` 会变。

## 10. 听歌报告（可选）

`qqmusic report --period d|w|m` 通过腾讯官方的 skill 接口获取听歌报告，内容包括常听的歌和歌手、流派分布、最常听歌的时段、连续听歌天数和听歌城市。它需要 `QQMUSIC_API_KEY`，用户可以在 https://y.qq.com/n/ryqq_v2/qqmusic_skills 自己创建。做推荐时，可以拿这份报告作为依据，贴近用户真实的收听习惯。

## 11. 口味分析（只读）

典型说法：「分析一下我最喜欢的音乐曲风」「我关注了哪些歌手？哪些关注了却很少收藏？」。

这里分析的是用户**收藏了什么**，不是**听了什么**。回答时要说清楚这一点。

```sh
F=$(qqmusic export | jq -r .path)

# 「我喜欢」的流派分布（代码对照见 concepts.md）
jq '{"1":"Pop","3":"Jazz","12":"Other","20":"Dance","21":"Easy Listening","22":"Electronica","23":"Folk","31":"New Age","33":"R&B","34":"Rap/Hip Hop","36":"Rock","37":"Soundtrack","50":"Alternative","58":"Singer Songwriter"} as $G
    | [.playlists[] | select(.dir_id == 201) | .songs[] | ($G[(.genre|tostring)] // "其他或未知")]
    | group_by(.) | map({genre: .[0], n: length}) | sort_by(-.n)' "$F"

# 年代分布
jq '[.playlists[] | select(.dir_id == 201) | .songs[] | ((.release_date // "")[:3] + "0s")]
    | group_by(.) | map({decade: .[0], n: length}) | sort_by(-.n)' "$F"

# 收藏最多的歌手（合唱的歌拆开，每位歌手各算一次）
jq '[.playlists[] | select(.dir_id == 201) | .songs[].singers[].name]
    | group_by(.) | map({artist: .[0], n: length}) | sort_by(-.n) | .[:10]' "$F"

# 用户给自建歌单打的标签，按歌单里的歌曲数加权
qqmusic playlists | jq '[.[] | .song_count as $n | .tags[] | {tag: ., n: $n}]
    | group_by(.tag) | map({tag: .[0].tag, playlists: length, songs: (map(.n) | add)}) | sort_by(-.songs)'

# 哪个歌单播放得最多（播放量是所有人的，见 concepts.md）
qqmusic playlists --fields name,song_count,listen_count | jq 'sort_by(-.listen_count) | .[:10]'

# 更省事的做法：qqmusic following --saved 直接给出每位关注歌手的 liked_songs / saved_songs

# 关注了，但所有歌单里一首都没收藏（按 mid 匹配）
jq '([.playlists[].songs[].singers[].mid] | unique) as $have
    | [.following_singers[] | select(.mid as $m | $have | index($m) | not) | .name]' "$F"

# 「我喜欢」里收藏了 3 首以上，却没关注（按 mid 匹配）
jq '([.following_singers[].mid]) as $f
    | [.playlists[] | select(.dir_id == 201) | .songs[].singers[]] | group_by(.mid)
    | map({artist: .[0].name, mid: .[0].mid, n: length})
    | map(select(.n >= 3 and (.mid as $m | $f | index($m) | not))) | sort_by(-.n)' "$F"
```

- 语种分布用第 2 节里的语种统计查询。
- 自建歌单的名字、标签和歌曲数，本身就说明了用户怎么给音乐分类，比如名字「RNB」「RAP」「Chill」，标签「R&B」「嘻哈」「安静」。标签是用户自己选的，比流派代码更接近用户的说法，可以拿来印证统计结果。有的歌单没打标签，结论不能只靠标签。
- 流派代码为 0 的歌比较多时，抽样用 `qqmusic song --stdin --detail` 补查文字流派。
- 结论用几句话概括，比如「以欧美 R&B 和说唱为主，偏爱 2020 年代的新歌」，再附上支撑结论的数字。
