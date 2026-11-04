-- Shenghua playback extension. Entity and AXI wrapper retain vendor licensing.
-- 8192 mono PCM16 samples; 48 kHz hardware clock; measured playback/underrun counters.
architecture IMP of user_logic is
  type ram_type is array(0 to 8191) of std_logic_vector(15 downto 0);
  signal ram : ram_type;
  attribute ram_style : string;
  attribute ram_style of ram : signal is "block";
  signal wrptr, rdptr : integer range 0 to 8191 := 0;
  signal level : integer range 0 to 8192 := 0;
  signal q : std_logic_vector(15 downto 0) := (others=>'0');
  signal enabled, running : std_logic := '0';
  signal played, missing, total : std_logic_vector(31 downto 0) := (others=>'0');
  signal fraction : integer range 0 to 12499 := 0;
  signal serial_count : std_logic_vector(6 downto 0) := (others=>'0');
  signal frame_load : std_logic;
  signal left_sample, right_sample : std_logic_vector(23 downto 0) := (others=>'0');
  signal data_out : std_logic_vector(31 downto 0);
begin
  -- 100 MHz * 768 / 12500 = 6.144 MHz half-bit events.
  -- 128 events per stereo frame gives precisely 48000 frames/s on average.
  BCLK <= serial_count(0);
  LRCLK <= serial_count(6);
  frame_load <= '1' when fraction>=11732 and serial_count=126 else '0';
  process(Bus2IP_Clk)
  begin
    if rising_edge(Bus2IP_Clk) then
      if Bus2IP_Resetn='0' then fraction<=0;serial_count<=(others=>'0');
      elsif fraction>=11732 then
        fraction<=fraction-11732;serial_count<=serial_count+1;
      else fraction<=fraction+768;
      end if;
      q<=ram(rdptr);
      if Bus2IP_Resetn='1' and enabled='1' and Bus2IP_WrCE(2)='1' and level<8192 then
        ram(wrptr)<=Bus2IP_Data(15 downto 0);
      end if;
    end if;
  end process;
  serializer: entity work.iis_ser port map(
    CLK_100MHZ=>Bus2IP_Clk,SCLK=>serial_count(0),LRCLK=>serial_count(6),
    EN=>'1',LDATA=>left_sample,RDATA=>right_sample,SDATA=>SDATA_O);
  process(Bus2IP_Clk)
    variable push, pop : boolean;
  begin
    if rising_edge(Bus2IP_Clk) then
      push:=enabled='1' and Bus2IP_WrCE(2)='1' and level<8192;
      pop:=running='1' and frame_load='1' and played<total and level>0;
      if Bus2IP_Resetn='0' then
        enabled<='0';running<='0';level<=0;wrptr<=0;rdptr<=0;
        played<=(others=>'0');missing<=(others=>'0');total<=(others=>'0');
        left_sample<=(others=>'0');right_sample<=(others=>'0');
      elsif Bus2IP_WrCE(0)='1' and Bus2IP_Data=x"A5000001" then
        enabled<='1';running<='0';level<=0;wrptr<=0;rdptr<=0;
        played<=(others=>'0');missing<=(others=>'0');total<=(others=>'0');
        left_sample<=(others=>'0');right_sample<=(others=>'0');
      elsif Bus2IP_WrCE(0)='1' and Bus2IP_Data=x"A5000000" then
        enabled<='0';running<='0';level<=0;
        left_sample<=(others=>'0');right_sample<=(others=>'0');
      else
        if Bus2IP_WrCE(0)='1' and Bus2IP_Data=x"A5000002" and enabled='1' then running<='1';end if;
        if Bus2IP_WrCE(1)='1' then total<=Bus2IP_Data;end if;
        if push then
          if wrptr=8191 then wrptr<=0;else wrptr<=wrptr+1;end if;
        end if;
        if pop then
          if rdptr=8191 then rdptr<=0;else rdptr<=rdptr+1;end if;
        end if;
        if push and not pop then level<=level+1;
        elsif pop and not push then level<=level-1;end if;
        if frame_load='1' and running='1' then
          if played<total then
            played<=played+1;
            if level>0 then left_sample<=q & x"00";right_sample<=q & x"00";
            else
              left_sample<=(others=>'0');right_sample<=(others=>'0');missing<=missing+1;
            end if;
          else
            running<='0';left_sample<=(others=>'0');right_sample<=(others=>'0');
          end if;
        end if;
      end if;
    end if;
  end process;
  process(Bus2IP_RdCE,played,missing,level,running,enabled)
  begin
    case Bus2IP_RdCE(4 downto 0) is
      when "10000" => data_out<=played;
      when "01000" => data_out<=missing;
      when "00100" => data_out<=conv_std_logic_vector(level,32);
      when "00010" => data_out<=x"53414631";
      when "00001" => data_out<=x"000000" & "000000" & running & enabled;
      when others => data_out<=(others=>'0');
    end case;
  end process;
  IP2Bus_Data<=data_out;
  IP2Bus_RdAck<=Bus2IP_RdCE(0) or Bus2IP_RdCE(1) or Bus2IP_RdCE(2) or Bus2IP_RdCE(3) or Bus2IP_RdCE(4);
  IP2Bus_WrAck<=Bus2IP_WrCE(0) or Bus2IP_WrCE(1) or Bus2IP_WrCE(2) or Bus2IP_WrCE(3) or Bus2IP_WrCE(4);
  IP2Bus_Error<='0';
end IMP;
