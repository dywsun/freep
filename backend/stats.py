"""Read sing-box's V2Ray StatsService without resetting remote counters."""

def query(port):
    import grpc
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    spec = descriptor_pb2.FileDescriptorProto(name='relay_stats.proto', package='relay', syntax='proto3')
    for name, fields in [('Query', []), ('Stat', [('name', 1, 9, None), ('value', 2, 3, None)]), ('Response', [('stat', 1, 11, '.relay.Stat')])]:
        m = spec.message_type.add(name=name)
        for fn, num, typ, target in fields:
            f = m.field.add(name=fn, number=num, type=typ, label=3 if target else 1)
            if target: f.type_name = target
    pool = descriptor_pool.DescriptorPool(); pool.Add(spec)
    response = message_factory.GetMessageClass(pool.FindMessageTypeByName('relay.Response'))
    with grpc.insecure_channel('127.0.0.1:' + str(port)) as channel:
        call = channel.unary_unary('/v2ray.core.app.stats.command.StatsService/QueryStats', request_serializer=lambda x: b'', response_deserializer=response.FromString)
        return {s.name: s.value for s in call(None, timeout=3).stat}
