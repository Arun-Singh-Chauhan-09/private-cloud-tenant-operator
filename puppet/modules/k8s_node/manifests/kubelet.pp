# @summary kubelet, kubeadm and kubectl from the pkgs.k8s.io repo for the pinned minor version.
#
# Debian/Ubuntu only. Packages are held so unattended upgrades cannot
# move a node to a different minor version than the control plane.
class k8s_node::kubelet {
  $minor   = $k8s_node::kubernetes_version
  $keyring = '/etc/apt/keyrings/kubernetes-apt-keyring.gpg'
  $repo    = "https://pkgs.k8s.io/core:/stable:/v${minor}/deb/"

  file { '/etc/apt/keyrings':
    ensure => directory,
    mode   => '0755',
  }

  exec { 'kubernetes-apt-key':
    command  => "/usr/bin/curl -fsSL ${repo}Release.key | /usr/bin/gpg --dearmor -o ${keyring}",
    creates  => $keyring,
    provider => shell,
    require  => File['/etc/apt/keyrings'],
  }

  file { '/etc/apt/sources.list.d/kubernetes.list':
    ensure  => file,
    mode    => '0644',
    content => "deb [signed-by=${keyring}] ${repo} /\n",
    require => Exec['kubernetes-apt-key'],
    notify  => Exec['apt-update-kubernetes'],
  }

  exec { 'apt-update-kubernetes':
    command     => '/usr/bin/apt-get update',
    refreshonly => true,
  }

  $packages = ['kubelet', 'kubeadm', 'kubectl']

  package { $packages:
    ensure  => installed,
    require => Exec['apt-update-kubernetes'],
  }

  exec { 'hold-kubernetes-packages':
    command  => "/usr/bin/apt-mark hold ${join($packages, ' ')}",
    unless   => '/usr/bin/test "$(/usr/bin/apt-mark showhold | /bin/grep -cE "^(kubelet|kubeadm|kubectl)$")" -eq 3',
    provider => shell,
    require  => Package[$packages],
  }

  service { 'kubelet':
    ensure  => running,
    enable  => true,
    require => Package['kubelet'],
  }
}
