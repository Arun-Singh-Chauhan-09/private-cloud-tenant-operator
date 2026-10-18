# @summary Kernel modules and sysctls required by kubelet and the CNI.
class k8s_node::kernel {
  $modules = ['overlay', 'br_netfilter']

  file { '/etc/modules-load.d/k8s.conf':
    ensure  => file,
    mode    => '0644',
    content => "${join($modules, "\n")}\n",
  }

  $modules.each |String $mod| {
    exec { "modprobe-${mod}":
      command => "/sbin/modprobe ${mod}",
      unless  => "/bin/grep -q '^${mod} ' /proc/modules",
      require => File['/etc/modules-load.d/k8s.conf'],
    }
  }

  file { '/etc/sysctl.d/99-kubernetes.conf':
    ensure  => file,
    mode    => '0644',
    content => @(SYSCTL),
      net.bridge.bridge-nf-call-iptables  = 1
      net.bridge.bridge-nf-call-ip6tables = 1
      net.ipv4.ip_forward                 = 1
      fs.inotify.max_user_instances       = 8192
      | SYSCTL
    notify  => Exec['sysctl-reload'],
  }

  exec { 'sysctl-reload':
    command     => '/sbin/sysctl --system',
    refreshonly => true,
    require     => Exec['modprobe-br_netfilter'],
  }
}
