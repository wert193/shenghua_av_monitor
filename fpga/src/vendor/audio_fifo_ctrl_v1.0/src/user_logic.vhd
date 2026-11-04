------------------------------------------------------------------------------
-- user_logic.vhd - entity/architecture pair
------------------------------------------------------------------------------
--
-- ***************************************************************************
-- ** Copyright (c) 1995-2012 Xilinx, Inc.  All rights reserved.            **
-- **                                                                       **
-- ** Xilinx, Inc.                                                          **
-- ** XILINX IS PROVIDING THIS DESIGN, CODE, OR INFORMATION "AS IS"         **
-- ** AS A COURTESY TO YOU, SOLELY FOR USE IN DEVELOPING PROGRAMS AND       **
-- ** SOLUTIONS FOR XILINX DEVICES.  BY PROVIDING THIS DESIGN, CODE,        **
-- ** OR INFORMATION AS ONE POSSIBLE IMPLEMENTATION OF THIS FEATURE,        **
-- ** APPLICATION OR STANDARD, XILINX IS MAKING NO REPRESENTATION           **
-- ** THAT THIS IMPLEMENTATION IS FREE FROM ANY CLAIMS OF INFRINGEMENT,     **
-- ** AND YOU ARE RESPONSIBLE FOR OBTAINING ANY RIGHTS YOU MAY REQUIRE      **
-- ** FOR YOUR IMPLEMENTATION.  XILINX EXPRESSLY DISCLAIMS ANY              **
-- ** WARRANTY WHATSOEVER WITH RESPECT TO THE ADEQUACY OF THE               **
-- ** IMPLEMENTATION, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OR        **
-- ** REPRESENTATIONS THAT THIS IMPLEMENTATION IS FREE FROM CLAIMS OF       **
-- ** INFRINGEMENT, IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS       **
-- ** FOR A PARTICULAR PURPOSE.                                             **
-- **                                                                       **
-- ***************************************************************************
--
------------------------------------------------------------------------------
-- Filename:          user_logic.vhd
-- Version:           1.00.a
-- Description:       User logic.
-- Date:              Wed Aug 15 18:20:40 2012 (by Create and Import Peripheral Wizard)
-- VHDL Standard:     VHDL'93
------------------------------------------------------------------------------
-- Naming Conventions:
--   active low signals:                    "*_n"
--   clock signals:                         "clk", "clk_div#", "clk_#x"
--   reset signals:                         "rst", "rst_n"
--   generics:                              "C_*"
--   user defined types:                    "*_TYPE"
--   state machine next state:              "*_ns"
--   state machine current state:           "*_cs"
--   combinatorial signals:                 "*_com"
--   pipelined or register delay signals:   "*_d#"
--   counter signals:                       "*cnt*"
--   clock enable signals:                  "*_ce"
--   internal version of output port:       "*_i"
--   device pins:                           "*_pin"
--   ports:                                 "- Names begin with Uppercase"
--   processes:                             "*_PROCESS"
--   component instantiations:              "<ENTITY_>I_<#|FUNC>"
------------------------------------------------------------------------------

-- DO NOT EDIT BELOW THIS LINE --------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.std_logic_arith.all;
use ieee.std_logic_unsigned.all;

-- DO NOT EDIT ABOVE THIS LINE --------------------

--USER libraries added here

------------------------------------------------------------------------------
-- Entity section
------------------------------------------------------------------------------
-- Definition of Generics:
--   C_NUM_REG                    -- Number of software accessible registers
--   C_SLV_DWIDTH                 -- Slave interface data bus width
--
-- Definition of Ports:
--   Bus2IP_Clk                   -- Bus to IP clock
--   Bus2IP_Resetn                -- Bus to IP reset
--   Bus2IP_Data                  -- Bus to IP data bus
--   Bus2IP_BE                    -- Bus to IP byte enables
--   Bus2IP_RdCE                  -- Bus to IP read chip enable
--   Bus2IP_WrCE                  -- Bus to IP write chip enable
--   IP2Bus_Data                  -- IP to Bus data bus
--   IP2Bus_RdAck                 -- IP to Bus read transfer acknowledgement
--   IP2Bus_WrAck                 -- IP to Bus write transfer acknowledgement
--   IP2Bus_Error                 -- IP to Bus error response
------------------------------------------------------------------------------

entity user_logic is
  generic
  (
    -- ADD USER GENERICS BELOW THIS LINE ---------------
    --USER generics added here
    -- ADD USER GENERICS ABOVE THIS LINE ---------------

    -- DO NOT EDIT BELOW THIS LINE ---------------------
    -- Bus protocol parameters, do not add to or delete
    C_NUM_REG                      : integer              := 5;
    C_SLV_DWIDTH                   : integer              := 32
    -- DO NOT EDIT ABOVE THIS LINE ---------------------
  );
  port
  (
    -- ADD USER PORTS BELOW THIS LINE ------------------
    BCLK    :  out  STD_LOGIC;
    LRCLK   :  out  STD_LOGIC;
    SDATA_I :  in   STD_LOGIC;
    SDATA_O :  out  STD_LOGIC;
    -- ADD USER PORTS ABOVE THIS LINE ------------------

    -- DO NOT EDIT BELOW THIS LINE ---------------------
    -- Bus protocol ports, do not add to or delete
    Bus2IP_Clk                     : in  std_logic;
    Bus2IP_Resetn                  : in  std_logic;
    Bus2IP_Data                    : in  std_logic_vector(C_SLV_DWIDTH-1 downto 0);
    Bus2IP_BE                      : in  std_logic_vector(C_SLV_DWIDTH/8-1 downto 0);
    Bus2IP_RdCE                    : in  std_logic_vector(C_NUM_REG-1 downto 0);
    Bus2IP_WrCE                    : in  std_logic_vector(C_NUM_REG-1 downto 0);
    IP2Bus_Data                    : out std_logic_vector(C_SLV_DWIDTH-1 downto 0);
    IP2Bus_RdAck                   : out std_logic;
    IP2Bus_WrAck                   : out std_logic;
    IP2Bus_Error                   : out std_logic
    -- DO NOT EDIT ABOVE THIS LINE ---------------------
  );

  attribute MAX_FANOUT : string;
  attribute SIGIS : string;

  attribute SIGIS of Bus2IP_Clk    : signal is "CLK";
  attribute SIGIS of Bus2IP_Resetn : signal is "RST";

end entity user_logic;

------------------------------------------------------------------------------
-- Architecture section
------------------------------------------------------------------------------

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
