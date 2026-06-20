+++
date = '2026-06-19T09:30:00+08:00'
draft = true
title = 'S905 / S905B 盒子从 eMMC 启动 Armbian：以 DM4036 为例'
tags = ["技术折腾", "Armbian", "电视盒子", "S905", "Linux", "eMMC"]
categories = ["技术"]
+++

![复古电视盒子与电路板](/images/tv-box-circuit-board.webp)

今天在网上闲逛的时候，偶然发现了一篇写得特别硬核的技术教程——关于怎么给 Amlogic S905 芯片的老电视盒子刷 Armbian，并且直接从 eMMC 启动。

这篇教程写得非常详细，从原理到步骤，再到常见坑点，都讲得很清楚。我觉得值得整理一下，分享给喜欢折腾的朋友。下面的内容基本保留了原文的结构和细节，只做了少量格式优化。

---

本文记录 DM4036 电视盒从 USB Armbian 迁移到 eMMC 启动的过程。设备为 Amlogic S905B / GXBB，设备树使用 `meson-gxbb-p201.dtb`，系统为 Armbian Trixie。

最终结果：
```text
不插 USB 存储，可直接从 eMMC 启动 Armbian
root = /dev/mmcblk2p1
LABEL = ROOT_EMMC
rootfs = ext4
kernel = 6.18.26-dm4036
```

本文适用于原厂 U-Boot + Amlogic EPT 分区表的 S905/S905B 盒子。文中的偏移、LBA 和文件大小以 DM4036 为例，**其他设备必须重新采集和计算。**

## 范围与风险

**前提条件：**
- Amlogic S905 / S905B / GXBB 盒子
- 已经能从 USB / TF / SD 启动 Armbian
- eMMC 上保留原厂 bootloader 和 Amlogic EPT 分区表
- 可以通过 TTL 串口进入 U-Boot

**不要直接执行：**
- `armbian-install`
- Armbian / ophub 镜像内置的写入 eMMC 脚本
- `fdisk` / `parted mklabel`
- 整盘 `dd` 镜像到 `/dev/mmcblk*`
- 覆盖 eMMC 开头的 bootloader / FIP / EPT 区域

这类盒子的 eMMC 开头通常包含原厂 bootloader、FIP、EPT 等结构，部分型号还可能使用高安或加密 bootloader。本文采用保留 bootloader 的方式，降低救砖难度。

## 实现概要

启动路径如下：
```text
保留原厂 U-Boot 和 EPT
在 eMMC cache 区裸写 zImage / uInitrd / dtb
在原 Android 分区区间创建 ext4 rootfs
内核用 blkdevparts 映射出 /dev/mmcblk2p1
U-Boot 用 mmc read 读取启动文件并执行 booti
```

内核必须启用：
```text
CONFIG_CMDLINE_PARTITION=y
```

否则无法通过 `blkdevparts=` 将 eMMC 原始区间映射为 Linux 块分区。

## 最终验证状态

本例最终使用 `instaboot` 起点作为 rootfs 起点，获得约 6.5G 的根文件系统空间。

内核命令行：
```text
blkdevparts=mmcblk2:6941573120@876609536(rootfs) root=LABEL=ROOT_EMMC rootwait rootfstype=ext4 rw console=ttyAML0,115200n8 console=tty0 no_console_suspend consoleblank=0 fsck.fix=yes fsck.repair=yes net.ifnames=0 max_loop=128 cgroup_enable=cpuset cgroup_memory=1 cgroup_enable=memory swapaccount=1
```

根文件系统：
```text
/dev/mmcblk2p1 ext4 ROOT_EMMC /
```

块设备：
```text
NAME          SIZE FSTYPE LABEL     MOUNTPOINTS
mmcblk2       7.3G
└─mmcblk2p1   6.5G ext4   ROOT_EMMC /
mmcblk2boot0    4M
mmcblk2boot1    4M
```

![Linux终端命令行界面](/images/linux-terminal-command-line.webp)

## 1. USB 启动 Armbian

USB 启动相关参考：<https://www.right.com.cn/forum/thread-8446282-1-1.html>

准备一个可以正常启动的 Armbian USB 盘，并通过 TTL 串口进入 U-Boot shell：

1. 打开串口连接软件。
2. 连接到带 `CH340` 字样的串口端口。
3. 给盒子通电。
4. 串口开始滚动输出后，连续按回车。
5. 出现 U-Boot shell 后输入启动命令。

在 U-Boot 中手动从 USB 启动 Armbian：
```text
usb start
fatload usb 0:1 0x1080000 zImage
fatload usb 0:1 0x13000000 uInitrd
fatload usb 0:1 0x1000000 dtb/amlogic/meson-gxbb-p201.dtb
setenv bootargs "root=LABEL=ROOTFS rootwait rootfstype=ext4 rw console=ttyAML0,115200n8 console=tty0 no_console_suspend consoleblank=0 fsck.fix=yes fsck.repair=yes net.ifnames=0 max_loop=128 cgroup_enable=cpuset cgroup_memory=1 cgroup_enable=memory swapaccount=1"
booti 0x1080000 0x13000000 0x1000000
```

如果 `usb 0:1` 找不到文件，先查看 USB 设备和分区：
```text
usb start
usb storage
fatls usb 0:1
fatls usb 1:1
fatls usb 2:1
```

能看到 `zImage`、`uInitrd`、`dtb/` 的分区就是启动分区。把上面的 `usb 0:1` 改成实际编号即可。

进入 USB Armbian 后采集基础信息：
```bash
uname -a
cat /proc/device-tree/model; echo
cat /proc/cmdline
lsblk -o NAME,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINTS
findmnt -no SOURCE,FSTYPE,LABEL,UUID,OPTIONS /
```

DM4036 初始状态示例：
```text
Machine model: Amlogic Meson GXBB P201 Development Board
USB root: /dev/sda2, LABEL=ROOTFS
USB boot: /dev/sda1, LABEL=BOOT
eMMC: /dev/mmcblk2, 7.28 GiB
```

检查当前内核是否支持 `blkdevparts`：
```bash
zgrep CONFIG_CMDLINE_PARTITION /proc/config.gz || grep CONFIG_CMDLINE_PARTITION /boot/config-$(uname -r)
```

本例原始 USB 内核没有启用：
```text
# CONFIG_CMDLINE_PARTITION is not set
```

所以需要重新编译或替换内核。

目标机建议先安装基础工具：
```bash
apt update
apt install -y rsync u-boot-tools gzip util-linux e2fsprogs
```

## 2. 读取原始 Android / EPT 分区布局

使用 `ampart` 只读查看 eMMC EPT。`ampart` 可从 7Ji 的 ampart 项目获取。

```bash
ampart /dev/mmcblk2
```

DM4036 原始 Android EPT 布局：
```text
bootloader    offset 0x00000000  size 0x00400000    4M
reserved      offset 0x02400000  size 0x04000000   64M
cache         offset 0x06c00000  size 0x20000000  512M
env           offset 0x27400000  size 0x00800000    8M
logo          offset 0x28400000  size 0x02000000   32M
recovery      offset 0x2ac00000  size 0x02000000   32M
rsv           offset 0x2d400000  size 0x00800000    8M
tee           offset 0x2e400000  size 0x00800000    8M
crypt         offset 0x2f400000  size 0x02000000   32M
misc          offset 0x31c00000  size 0x02000000   32M
instaboot     offset 0x34400000  size 0x20000000  512M
boot          offset 0x54c00000  size 0x02000000   32M
system        offset 0x57400000  size 0x40000000    1G
recovery_bak  offset 0x97c00000  size 0x02000000   32M
backup        offset 0x9a400000  size 0x20000000  512M
data          offset 0xbac00000  size 0x117400000 4.36G
```

本例最终保留：
```text
bootloader / reserved / cache / env / logo / recovery / rsv / tee / crypt / misc
```

并覆盖：
```text
instaboot / boot / system / recovery_bak / backup / data
```

这会破坏 Android 系统，但不覆盖 eMMC 开头 bootloader 区，也不覆盖 U-Boot 环境区。若仍想保留更多 Android 分区，可以只使用 `data` 区，见下一节的保守方案。

注意：`blkdevparts` 使用 Linux 块设备名，例如 `mmcblk2`，不是 `/dev/mmcblk2`。

## 3. 选择 rootfs 区域

### 方案 A：保守 data 区

只使用 Android 的 `data` 区：
```bash
ROOT_OFF=$((0xbac00000))
ROOT_SIZE=$(( $(blockdev --getsize64 /dev/mmcblk2) - ROOT_OFF ))
```

DM4036 上得到：
```text
ROOT_OFF=3133145088
ROOT_SIZE=4685037568
blkdevparts=mmcblk2:4685037568@3133145088(rootfs)
```

优点是覆盖面小；缺点是 rootfs 只有约 4.4G。

本例早期直接使用 EPT 中的 `data size = 0x117400000` 启动时遇到过 4K 差异：
```text
The filesystem size (according to the superblock) is 1143808 blocks
The physical size of the device is 1143807 blocks
EXT4-fs (mmcblk2p1): bad geometry
```

后来改用 "eMMC 总字节数 - 起点" 作为 `blkdevparts` size 后正常。

### 方案 B：从 instaboot 到盘尾

如果 Android 已经不重要，可以从 `instaboot` 起点一直用到盘尾：
```bash
ROOT_OFF=$((0x34400000))
ROOT_SIZE=$(( $(blockdev --getsize64 /dev/mmcblk2) - ROOT_OFF ))
```

DM4036 上得到：
```text
ROOT_OFF=876609536
ROOT_SIZE=6941573120
blkdevparts=mmcblk2:6941573120@876609536(rootfs)
```

本例最终采用这个方案，rootfs 块设备约 6.5G，ext4 可用空间约 6.3G。

## 4. 做最小备份

如果 Android 系统不重要，可以不做完整 eMMC 备份，但至少建议备份 eMMC 头部、环境区和 EPT 输出。

```bash
TS=$(date +%Y%m%d-%H%M%S)
BK=/root/s905-emmc-backup-$TS
mkdir -p "$BK"
dd if=/dev/mmcblk2 of="$BK/emmc-head-128M.bin" bs=4M count=32 status=progress
gzip -k "$BK/emmc-head-128M.bin"
dd if=/dev/mmcblk2 of="$BK/emmc-env-8M.bin" bs=1M skip=$((0x27400000 / 1024 / 1024)) count=8 status=progress
gzip -k "$BK/emmc-env-8M.bin"
ampart /dev/mmcblk2 > "$BK/ampart-before.txt" 2>&1 || true
ls -lh "$BK"
```

本例实际保留了：
```text
emmc-head-128M.bin.gz
emmc-env-8M.bin.gz
ampart-before.txt
```

![电路板上的芯片特写](/images/chip-motherboard-closeup.webp)

## 5. 编译启用 CMDLINE_PARTITION 的内核

本例在一台 x86 Ubuntu 主机上交叉编译，避免在盒子上长时间编译。

参考项目：
```text
https://github.com/ophub/amlogic-s9xxx-armbian
https://github.com/unifreq/linux-6.18.y
```

安装依赖示例：
```bash
sudo apt update
sudo apt install -y git make gcc-aarch64-linux-gnu bc bison flex libssl-dev libelf-dev dwarves u-boot-tools rsync xz-utils
```

拉取源码：
```bash
mkdir -p ~/work/kernel-build ~/work
cd ~/work
git clone --depth=1 https://github.com/ophub/amlogic-s9xxx-armbian.git
git clone --depth=1 https://github.com/unifreq/linux-6.18.y.git ~/work/kernel-build/linux-6.18.y
```

以目标机原始内核配置为基础，只打开 `CMDLINE_PARTITION`：
```bash
cd ~/work/kernel-build/linux-6.18.y
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- mrproper
# config-6.18.target 来自目标机 /boot/config-*
cp /path/to/config-6.18.target .config
scripts/config -e CMDLINE_PARTITION
scripts/config --set-str LOCALVERSION ""
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION=-dm4036 olddefconfig
```

编译：
```bash
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION=-dm4036 Image modules dtbs -j$(( $(nproc) - 1 ))
KREL=$(make -s ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION=-dm4036 kernelrelease)
echo "$KREL"
```

本例得到：
```text
6.18.26-dm4036
```

安装模块和打包：
```bash
OUT=~/work/kernel-build/output-dm4036
rm -rf "$OUT"
mkdir -p "$OUT/root/boot/dtb/amlogic"
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION=-dm4036 INSTALL_MOD_PATH="$OUT/root" modules_install
mkdir -p "$OUT/root/usr/lib/modules"
mv "$OUT/root/lib/modules" "$OUT/root/usr/lib/modules/"
rmdir "$OUT/root/lib"
cp arch/arm64/boot/Image "$OUT/root/boot/zImage-$KREL"
cp System.map "$OUT/root/boot/System.map-$KREL"
cp .config "$OUT/root/boot/config-$KREL"
cp arch/arm64/boot/dts/amlogic/*.dtb "$OUT/root/boot/dtb/amlogic/"
find "$OUT/root/usr/lib/modules/$KREL" -name build -o -name source | xargs -r rm -f
tar -C "$OUT/root" -czf ~/work/kernel-build/s905-kernel-$KREL.tar.gz .
sha256sum ~/work/kernel-build/s905-kernel-$KREL.tar.gz > ~/work/kernel-build/s905-kernel-$KREL.tar.gz.sha256
```

## 6. 在 USB 系统中安装新内核

把内核包复制到目标机后安装：
```bash
tar -C / -xzf s905-kernel-6.18.26-dm4036.tar.gz
```

备份原 USB `/boot` 默认文件：
```bash
TS=$(date +%Y%m%d-%H%M%S)
BK=/root/s905-boot-backup-$TS
mkdir -p "$BK"
cp -a /boot/zImage "$BK/zImage.old"
cp -a /boot/uInitrd "$BK/uInitrd.old"
cp -a /boot/dtb/amlogic/meson-gxbb-p201.dtb "$BK/meson-gxbb-p201.dtb.old"
cp -a /boot/uEnv.txt "$BK/uEnv.txt.old" 2>/dev/null || true
```

生成 `uInitrd`，并把新内核切成默认启动文件：
```bash
KREL=6.18.26-dm4036
update-initramfs -c -k "$KREL"
mkimage -A arm64 -O linux -T ramdisk -C gzip -n uInitrd \
  -d "/boot/initrd.img-$KREL" "/boot/uInitrd-$KREL"
cp -a "/boot/zImage-$KREL" /boot/zImage
cp -a "/boot/uInitrd-$KREL" /boot/uInitrd
cp -a "/boot/dtb/amlogic/meson-gxbb-p201.dtb" "/boot/dtb/amlogic/meson-gxbb-p201-$KREL.dtb"
cp -a "/boot/dtb/amlogic/meson-gxbb-p201-$KREL.dtb" "/boot/dtb/amlogic/meson-gxbb-p201.dtb"
sync
```

重启 USB 系统，确认新内核能正常启动：
```bash
uname -r
zgrep CONFIG_CMDLINE_PARTITION /proc/config.gz || grep CONFIG_CMDLINE_PARTITION /boot/config-$(uname -r)
```

期望：
```text
6.18.26-dm4036
CONFIG_CMDLINE_PARTITION=y
```

也可以只把该内核注入 eMMC rootfs 和 cache 区，USB 系统本身继续使用原内核。本例两种方式都验证过。

## 7. 在 eMMC 创建 rootfs

下面以最终采用的 `instaboot` 起点为例。若采用保守 `data` 区方案，只需要替换 `ROOT_OFF` 和 `ROOT_SIZE`。

不要对整块 eMMC 分区。只把选定区间映射成 loop 设备，然后在 loop 上创建 ext4。

```bash
EMMC=/dev/mmcblk2
ROOT_OFF=$((0x34400000))
ROOT_SIZE=$(( $(blockdev --getsize64 "$EMMC") - ROOT_OFF ))
MNT=/mnt/emmcroot
mkdir -p "$MNT"
LOOP=$(losetup --find --show --offset "$ROOT_OFF" --sizelimit "$ROOT_SIZE" "$EMMC")
echo "$LOOP"
mkfs.ext4 -F -L ROOT_EMMC "$LOOP"
mount "$LOOP" "$MNT"
```

把当前 USB Armbian 同步到 eMMC rootfs：
```bash
rsync -aAXH --numeric-ids --info=progress2 / "$MNT" \
  --exclude='/dev/*' \
  --exclude='/proc/*' \
  --exclude='/sys/*' \
  --exclude='/tmp/*' \
  --exclude='/run/*' \
  --exclude='/mnt/*' \
  --exclude='/media/*' \
  --exclude='/lost+found' \
  --exclude='/var/cache/apt/archives/*.deb'
```

写入 eMMC rootfs 的 `/etc/fstab`：
```bash
cat >"$MNT/etc/fstab" <<'EOF'
LABEL=ROOT_EMMC  /      ext4  defaults,noatime,nodiratime,commit=600,errors=remount-ro  0 1
tmpfs            /tmp   tmpfs defaults,nosuid                                             0 0
EOF
```

如果 USB 系统还没有运行自编译内核，需要把内核包注入 eMMC rootfs：
```bash
KREL=6.18.26-dm4036
tar -C "$MNT" -xzf s905-kernel-$KREL.tar.gz
cp -a "$MNT/boot/zImage-$KREL" "$MNT/boot/zImage"
if [ -s "$MNT/boot/dtb/amlogic/meson-gxbb-p201-$KREL.dtb" ]; then
  cp -a "$MNT/boot/dtb/amlogic/meson-gxbb-p201-$KREL.dtb" \
    "$MNT/boot/dtb/amlogic/meson-gxbb-p201.dtb"
fi
mount --bind /dev "$MNT/dev"
mount --bind /proc "$MNT/proc"
mount --bind /sys "$MNT/sys"
chroot "$MNT" depmod "$KREL"
chroot "$MNT" update-initramfs -c -k "$KREL"
mkimage -A arm64 -O linux -T ramdisk -C gzip -n uInitrd \
  -d "$MNT/boot/initrd.img-$KREL" "$MNT/boot/uInitrd-$KREL"
rm -f "$MNT/boot/uInitrd"
cp -a "$MNT/boot/uInitrd-$KREL" "$MNT/boot/uInitrd"
umount "$MNT/sys" "$MNT/proc" "$MNT/dev"
```

收尾前可以检查：
```bash
df -hT "$MNT"
blkid "$LOOP"
ls -lh "$MNT/boot/zImage" "$MNT/boot/uInitrd" "$MNT/boot/dtb/amlogic/meson-gxbb-p201.dtb"
```

## 8. 裸写 zImage / uInitrd / dtb 到 cache 区

U-Boot 不认识 Linux 启动后的 `blkdevparts`，所以不能指望 U-Boot 从 `/dev/mmcblk2p1` 读取 `/boot`。这里把启动文件裸写进 eMMC `cache` 区的固定位置。

DM4036 使用的布局：
```text
zImage  offset 0x06c00000, LBA 0x36000
uInitrd offset 0x0ac00000, LBA 0x56000
dtb     offset 0x0cc00000, LBA 0x66000
```

写入前必须按当前文件大小重新计算 block count。若 `uInitrd` 是符号链接，要用 `stat -L`：

```bash
EMMC=/dev/mmcblk2
CACHE_OFF=$((0x06c00000))
KERNEL="$MNT/boot/zImage"
INITRD="$MNT/boot/uInitrd"
DTB="$MNT/boot/dtb/amlogic/meson-gxbb-p201.dtb"
K_LBA=$(( (CACHE_OFF + 0*1024*1024) / 512 ))
I_LBA=$(( (CACHE_OFF + 64*1024*1024) / 512 ))
D_LBA=$(( (CACHE_OFF + 96*1024*1024) / 512 ))
K_SIZE=$(stat -Lc%s "$KERNEL")
I_SIZE=$(stat -Lc%s "$INITRD")
D_SIZE=$(stat -Lc%s "$DTB")
K_CNT=$(( (K_SIZE + 511) / 512 ))
I_CNT=$(( (I_SIZE + 511) / 512 ))
D_CNT=$(( (D_SIZE + 511) / 512 ))
printf 'K_LBA=0x%x K_CNT=0x%x K_SIZE=%s\n' "$K_LBA" "$K_CNT" "$K_SIZE"
printf 'I_LBA=0x%x I_CNT=0x%x I_SIZE=%s\n' "$I_LBA" "$I_CNT" "$I_SIZE"
printf 'D_LBA=0x%x D_CNT=0x%x D_SIZE=%s\n' "$D_LBA" "$D_CNT" "$D_SIZE"
```

本例最终值：
```text
K_LBA=0x36000 K_CNT=0x16995 K_SIZE=47393280
I_LBA=0x56000 I_CNT=0xbc1d I_SIZE=24656070
D_LBA=0x66000 D_CNT=0x4b    D_SIZE=38099
```

写入并校验：
```bash
dd if="$KERNEL" of="$EMMC" bs=512 seek="$K_LBA" conv=notrunc,fsync status=progress
dd if="$INITRD" of="$EMMC" bs=512 seek="$I_LBA" conv=notrunc,fsync status=progress
dd if="$DTB"    of="$EMMC" bs=512 seek="$D_LBA" conv=notrunc,fsync status=progress
sync
dd if="$EMMC" bs=512 skip="$K_LBA" count="$K_CNT" status=none | cmp -n "$K_SIZE" "$KERNEL" -
dd if="$EMMC" bs=512 skip="$I_LBA" count="$I_CNT" status=none | cmp -n "$I_SIZE" "$INITRD" -
dd if="$EMMC" bs=512 skip="$D_LBA" count="$D_CNT" status=none | cmp -n "$D_SIZE" "$DTB" -
```

成功后卸载 rootfs：
```bash
sync
umount "$MNT"
losetup -d "$LOOP"
```

## 9. U-Boot 临时启动测试

强烈建议先通过 TTL 串口临时启动，确认成功后再 `saveenv`。

先确认 eMMC 在 U-Boot 里的编号：
```text
mmc list
mmc dev 0
mmc info
mmc dev 1
mmc info
```

DM4036 上 eMMC 是 U-Boot 的 `mmc 1`。最终临时启动命令：

```text
mmc dev 1
mmc read 0x1080000 0x36000 0x16995
mmc read 0x13000000 0x56000 0xbc1d
mmc read 0x1000000 0x66000 0x4b
setenv bootargs "blkdevparts=mmcblk2:6941573120@876609536(rootfs) root=LABEL=ROOT_EMMC rootwait rootfstype=ext4 rw console=ttyAML0,115200n8 console=tty0 no_console_suspend consoleblank=0 fsck.fix=yes fsck.repair=yes net.ifnames=0 max_loop=128 cgroup_enable=cpuset cgroup_memory=1 cgroup_enable=memory swapaccount=1"
booti 0x1080000 0x13000000 0x1000000
```

如果使用保守 `data` 区方案，需要把 `blkdevparts` 改成：
```text
blkdevparts=mmcblk2:4685037568@3133145088(rootfs)
```

如果能进系统，用 SSH 验证：
```bash
uname -r
cat /proc/cmdline
findmnt -no SOURCE,FSTYPE,LABEL,UUID,OPTIONS /
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINTS
```

期望：
```text
uname -r = 6.18.26-dm4036
/ = /dev/mmcblk2p1 ext4 ROOT_EMMC
```

## 10. 写入永久 U-Boot 环境

确认临时启动成功后，再进入 U-Boot 保存环境变量：

```text
setenv bootdelay 3
setenv emmcboot 'mmc dev 1; mmc read 0x1080000 0x36000 0x16995; mmc read 0x13000000 0x56000 0xbc1d; mmc read 0x1000000 0x66000 0x4b; setenv bootargs blkdevparts=mmcblk2:6941573120@876609536(rootfs) root=LABEL=ROOT_EMMC rootwait rootfstype=ext4 rw console=ttyAML0,115200n8 console=tty0 no_console_suspend consoleblank=0 fsck.fix=yes fsck.repair=yes net.ifnames=0 max_loop=128 cgroup_enable=cpuset cgroup_memory=1 cgroup_enable=memory swapaccount=1; booti 0x1080000 0x13000000 0x1000000'
setenv bootcmd 'run emmcboot; run storeboot'
saveenv
reset
```

说明：
- `emmcboot` 是 eMMC Armbian 启动路径。
- `bootcmd` 后面保留 `run storeboot`，用于在 `emmcboot` 失败时尝试回到原厂启动流程。
- 本例没有使用 Linux 下的 `fw_setenv`，因为该 Amlogic 环境区格式无法被常规 `fw_printenv` 稳定识别。串口 U-Boot 下 `saveenv` 更可靠。

## 11. 最终验证

第一次永久启动时可以先保留 USB 插着，确认没有继续使用 USB root：
```bash
cat /proc/cmdline
findmnt -no SOURCE,FSTYPE,LABEL,UUID,OPTIONS /
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINTS
df -hT /
```

本例永久启动后，即使 USB 仍插着，根分区已经是：
```text
/dev/mmcblk2p1 ext4 ROOT_EMMC /
```

随后关机，拔掉 USB，再上电。最终验证：
```text
USB 设备不存在
/ 仍为 /dev/mmcblk2p1
```

到这里，目标完成。

---

## 常见问题

### 1. 修改 `/boot/uEnv.txt` 没有效果

本例原厂 U-Boot 的 `bootcmd` 会硬编码设置 `bootargs`，并不真正使用 `uEnv.txt` 中的 `APPEND`。所以只改 USB `/boot/uEnv.txt` 不会切换 rootfs。

解决方法是通过 TTL 串口进入 U-Boot，先手动临时启动验证，再用 `saveenv` 保存 `bootcmd`。本文只记录 TTL 手动方式。

### 2. 不要使用内置写入 eMMC 脚本

不要使用 Armbian / ophub 镜像内置的写入 eMMC 脚本。该类脚本通常面向可标准分区或已适配安装流程的设备，可能会改写分区表、覆盖启动区域或假设 U-Boot 能按常规文件系统方式读取 `/boot`。

DM4036 这类原厂 U-Boot + Amlogic EPT 布局的盒子，应按本文方式保留 bootloader 和 EPT，只在明确计算过的 eMMC 区间写入 rootfs，并把启动文件裸写到 `cache` 区固定 LBA。

### 3. `fw_printenv` / `fw_setenv` 不能用

本例安装 `libubootenv-tool` 后尝试读取 eMMC `env` 区，但常规配置无法正确识别 Amlogic 环境格式。因此没有在 Linux 下写 U-Boot 环境。

建议：
- 只用 `dd` 备份 `env` 区。
- 永久修改通过 TTL 串口下的 U-Boot `saveenv` 完成。

### 4. `EXT4-fs: bad geometry`

现象：
```text
filesystem size = 1143808 blocks
device size     = 1143807 blocks
```

处理：
- 不要急着重做 rootfs。
- 先确认 `blkdevparts` 的 size 是否比实际 rootfs 少 4K。
- 本例在 `data` 区方案中把 size 从 `4685033472` 改为 `4685037568` 后正常启动。

### 5. 换内核后必须重算 LBA count

`mmc read` 的第三个参数是 512 字节 block 数。换了内核、initrd 或 dtb 后，必须重新计算：
```bash
COUNT=$(( ($(stat -Lc%s /path/to/file) + 511) / 512 ))
printf '0x%x\n' "$COUNT"
```

如果 `/boot/uInitrd` 是符号链接，一定要用 `stat -L`。本例曾经因为没有跟随符号链接，把 `uInitrd` 误算成 `0x1`，这个值不能用于 U-Boot。

### 6. USB 启动后 eMMC 设备名和最终启动设备名可能不同

设备名由内核枚举顺序决定。准备 rootfs 时要以当前 USB 系统实际看到的设备为准，例如 `/dev/mmcblk2`。最终启动时 `blkdevparts=` 里的名字也必须匹配自编译内核启动后的名字。

本例最终自编译内核下 eMMC 是 `mmcblk2`，所以使用：
```text
blkdevparts=mmcblk2:6941573120@876609536(rootfs)
```

## 回退思路

如果写入永久 `bootcmd` 后启动失败：
1. 插回 USB 启动盘。
2. 通过 TTL 进入 U-Boot。
3. 执行 `run storeboot` 或手动走 USB 启动命令。
4. 重新检查 `mmc dev` 编号、`mmc read` LBA/count、`blkdevparts` size 和 rootfs 标签。

如果只是 Armbian rootfs 损坏，bootloader 通常仍可恢复，因为本方案没有覆盖 eMMC 开头的 bootloader 区。

## 参考

- ophub amlogic-s9xxx-armbian: https://github.com/ophub/amlogic-s9xxx-armbian
- ophub compile-kernel: https://github.com/ophub/amlogic-s9xxx-armbian/tree/main/compile-kernel
- unifreq linux-6.18.y: https://github.com/unifreq/linux-6.18.y
- Linux kernel cmdline partition: https://www.kernel.org/doc/html/latest/block/cmdline-partition.html
- ampart / EPT 说明: https://7ji.github.io/embedded/2022/11/11/ept-with-ampart.html
