class Vifi < Formula
  include Language::Python::Virtualenv

  desc "Universal Voice Layer for AI Agents, MCP, and macOS"
  homepage "https://voicefi.org"
  url "https://github.com/atxatlarge-code/voicefi/archive/refs/heads/main.tar.gz"
  version "0.1.0"
  license "Apache-2.0"

  depends_on "python@3.12"
  depends_on "portaudio"
  depends_on "ffmpeg" => :optional

  def install
    virtualenv_install_with_resources
    bin.install_symlink libexec/"bin/voicefi" => "vifi"
    bin.install_symlink libexec/"bin/voicefi" => "vg"
  end

  def post_install
    system bin/"vifi", "setup" rescue nil
    system bin/"vifi", "autostart" rescue nil
  end

  def caveats
    <<~EOS
      VoiceFi (vifi) has been installed and configured!

      Dynamic Island HUD and Agent Voice Hooks are active.
      To launch the interactive onboarding tour or audio test anytime:
        vifi onboarding
        vifi voice test
        vifi panel
    EOS
  end

  test do
    assert_match "VoiceFi", shell_output("#{bin}/vifi --help")
  end
end
