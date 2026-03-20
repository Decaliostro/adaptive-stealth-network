FUNCTION score(route):

  score =
      latency * 0.4
    + packet_loss * 2
    - throughput * 0.3
    + error_count * 100

  RETURN score