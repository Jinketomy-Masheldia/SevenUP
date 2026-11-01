#!/bin/sh
umask 077
/bin/sleep 20
/usr/sbin/ioreg -l -w 0 > /private/var/log/ssh1-ioreg-20.txt 2> /private/var/log/ssh1-ioreg-20.err
/bin/ps -ax > /private/var/log/ssh1-ps-20.txt 2>&1
/usr/sbin/sysctl kern.bootargs > /private/var/log/ssh1-bootargs.txt 2>&1
/bin/sleep 40
/usr/sbin/ioreg -l -w 0 > /private/var/log/ssh1-ioreg-60.txt 2> /private/var/log/ssh1-ioreg-60.err
/bin/ps -ax > /private/var/log/ssh1-ps-60.txt 2>&1
