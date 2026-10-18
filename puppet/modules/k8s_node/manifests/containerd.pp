# @summary containerd with the systemd cgroup driver, optionally with the NVIDIA runtime.
class k8s_node::containerd {
  package { 'containerd':
    ensure => $k8s_node::containerd_version,
  }

  file { '/etc/containerd':
    ensure => directory,
    mode   => '0755',
  }

  file { '/etc/containerd/config.toml':
    ensure  => file,
    mode    => '0644',
    content => epp('k8s_node/containerd-config.toml.epp', {
      'pause_image' => $k8s_node::pause_image,
      'enable_gpu'  => $k8s_node::enable_gpu,
    }),
    require => [Package['containerd'], File['/etc/containerd']],
    notify  => Service['containerd'],
  }

  service { 'containerd':
    ensure => running,
    enable => true,
  }
}
