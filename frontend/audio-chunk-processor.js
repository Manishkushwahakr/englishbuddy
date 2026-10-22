class AudioChunkProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.chunkFrameCount = Math.ceil(sampleRate * 5);
    this.frameOffset = 0;
    this.samples = new Float32Array(this.chunkFrameCount);
  }

  process(inputs, outputs) {
    const channels = inputs[0];
    const outputChannels = outputs[0];
    if (outputChannels) {
      outputChannels.forEach((channel) => channel.fill(0));
    }
    if (!channels || channels.length === 0) return true;

    const frameCount = channels[0].length;
    for (let frame = 0; frame < frameCount; frame += 1) {
      let sample = 0;
      for (const channel of channels) {
        sample += channel[frame] || 0;
      }
      this.samples[this.frameOffset] = sample / channels.length;
      this.frameOffset += 1;

      if (this.frameOffset === this.chunkFrameCount) {
        const completedSamples = this.samples;
        this.samples = new Float32Array(this.chunkFrameCount);
        this.frameOffset = 0;
        this.port.postMessage({
          samples: completedSamples.buffer,
          sampleRate,
        }, [completedSamples.buffer]);
      }
    }

    return true;
  }
}

registerProcessor("improbuddy-audio-chunk", AudioChunkProcessor);
