# Example node classification. Apply on a test VM with:
#   sudo puppet apply --modulepath=puppet/modules puppet/examples/site.pp
node default {
  class { 'k8s_node':
    kubernetes_version => '1.31',
    enable_gpu         => false,
  }
}
