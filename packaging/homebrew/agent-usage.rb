class AgentUsage < Formula
  include Language::Python::Virtualenv

  desc "Inspect local auth state and usage context for Codex, Claude Code, and Cursor"
  homepage "https://github.com/supdub/agent-usage-cli"
  url "https://github.com/supdub/agent-usage-cli/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_SOURCE_TARBALL_SHA256"
  license "MIT"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    output = shell_output("#{bin}/au codex")
    assert_match "\"providers\"", output
  end
end
