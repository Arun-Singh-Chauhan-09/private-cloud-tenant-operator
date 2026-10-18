# @summary kubelet expects swap off: disable it now and on reboot.
class k8s_node::swap {
  exec { 'swapoff':
    command  => '/sbin/swapoff -a',
    onlyif   => '/usr/bin/test -n "$(/sbin/swapon --show --noheadings)"',
    provider => shell,
  }

  exec { 'comment-swap-in-fstab':
    command => "/bin/sed -i -E 's@^([^#].*\\sswap\\s.*)@# \\1@' /etc/fstab",
    onlyif  => "/bin/grep -qE '^[^#].*\\sswap\\s' /etc/fstab",
  }
}
