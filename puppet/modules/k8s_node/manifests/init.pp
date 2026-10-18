# @summary Prepares a bare-metal Linux host to join a Kubernetes cluster.
#
# Uses only core Puppet resource types so it has no Forge dependencies.
#
# @param kubernetes_version  Minor version pinned for kubelet/kubeadm/kubectl, e.g. '1.31'.
# @param containerd_version  Package version string, or 'installed'.
# @param pause_image         Sandbox image containerd should use.
# @param enable_gpu          Install the NVIDIA container toolkit runtime config on GPU nodes.
#
# @example
#   class { 'k8s_node':
#     kubernetes_version => '1.31',
#     enable_gpu         => $facts['gpu_present'],
#   }
class k8s_node (
  Pattern[/^\d+\.\d+$/] $kubernetes_version = '1.31',
  String[1]             $containerd_version = 'installed',
  String[1]             $pause_image        = 'registry.k8s.io/pause:3.10',
  Boolean               $enable_gpu         = false,
) {
  contain k8s_node::kernel
  contain k8s_node::swap
  contain k8s_node::containerd
  contain k8s_node::kubelet

  Class['k8s_node::kernel']
  -> Class['k8s_node::swap']
  -> Class['k8s_node::containerd']
  -> Class['k8s_node::kubelet']
}
